"""KB source-document loader.

Reads markdown files from `backend/data/seed/kb/` and turns each into a
`SourceDocument`. Doc metadata (doc_type, product_area, plan_scope, version, title)
comes from YAML front-matter at the top of each file, not from the filename or
directory — keeps the loader agnostic to how the KB is organized on disk.
"""

import re
from pathlib import Path

import yaml

from app.db.seed import SEED_DIR
from app.schemas.rag import DocType, SourceDocument

# Built on SEED_DIR (app/db/seed.py) rather than a second independent
# Path(__file__).resolve() computation: a duplicate path calculation for the
# same directory can silently diverge from the original if either file moves.
KB_DIR = SEED_DIR / "kb"

# Captures the YAML block between the two '---' delimiters (group 1) and everything
# after the closing delimiter (group 2). DOTALL so '.' matches newlines inside the
# front-matter block; non-greedy so it stops at the *first* closing '---', not the
# last one in the file.
_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

_REQUIRED_FRONT_MATTER_FIELDS = ("title", "doc_type")


def load_documents(kb_dir: Path = KB_DIR) -> list[SourceDocument]:
    """Load every `.md` file under `kb_dir` into a `SourceDocument`.

    Parses the YAML front-matter block (--- delimited, at the top of the file) into
    `title`/`doc_type`/`product_area`/`plan_scope`/`version`; everything after the
    closing `---` becomes `content`. A file missing a required front-matter field
    (`title`, `doc_type`) raises, rather than silently falling back to a default —
    an untagged KB doc is a content bug, not a case to paper over.

    Files are visited in sorted path order so ingestion runs are deterministic
    regardless of filesystem directory-listing order.
    """
    return [_load_document(path, kb_dir) for path in sorted(kb_dir.rglob("*.md"))]


def _load_document(path: Path, kb_dir: Path) -> SourceDocument:
    front_matter, content = _parse_front_matter(path)

    missing_fields = [field for field in _REQUIRED_FRONT_MATTER_FIELDS if not front_matter.get(field)]
    if missing_fields:
        raise ValueError(f"{path}: missing required front-matter field(s): {', '.join(missing_fields)}")

    return SourceDocument(
        title=front_matter["title"],
        doc_type=DocType(front_matter["doc_type"]),
        product_area=front_matter.get("product_area"),
        plan_scope=front_matter.get("plan_scope"),
        # str(...): an unquoted front-matter value like `version: 1.0` parses as
        # a YAML float, and SourceDocument.version expects a str.
        version=str(front_matter.get("version", "1.0")),
        # Relative to kb_dir, not absolute: the dedup key ingestion.py matches on
        # must stay stable across machines/checkouts, where kb_dir's absolute path
        # differs.
        source=str(path.relative_to(kb_dir)),
        content=content.strip(),
    )


def _parse_front_matter(path: Path) -> tuple[dict, str]:
    match = _FRONT_MATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{path}: missing YAML front-matter block (expected '---' delimiters)")

    front_matter = yaml.safe_load(match.group(1)) or {}
    return front_matter, match.group(2)
