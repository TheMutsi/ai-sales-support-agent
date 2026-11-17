import re
from pathlib import Path

import yaml

from app.core.config import SEED_DIR
from app.schemas.rag import DocType, SourceDocument

KB_DIR = SEED_DIR / "kb"

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

_REQUIRED_FRONT_MATTER_FIELDS = ("title", "doc_type", "when_to_use")


def load_documents(kb_dir: Path = KB_DIR) -> list[SourceDocument]:
    return [_load_document(path, kb_dir) for path in sorted(kb_dir.rglob("*.md"))]


def _load_document(path: Path, kb_dir: Path) -> SourceDocument:
    front_matter, content = _parse_front_matter(path)

    missing_fields = [field for field in _REQUIRED_FRONT_MATTER_FIELDS if not front_matter.get(field)]
    if missing_fields:
        raise ValueError(f"{path}: missing required front-matter field(s): {', '.join(missing_fields)}")

    return SourceDocument(
        title=front_matter["title"],
        when_to_use=str(front_matter["when_to_use"]),
        doc_type=DocType(front_matter["doc_type"]),
        product_area=front_matter.get("product_area"),
        plan_scope=front_matter.get("plan_scope"),
        version=str(front_matter.get("version", "1.0")),
        source=str(path.relative_to(kb_dir)),
        content=content.strip(),
    )


def _parse_front_matter(path: Path) -> tuple[dict, str]:
    match = _FRONT_MATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{path}: missing YAML front-matter block (expected '---' delimiters)")

    front_matter = yaml.safe_load(match.group(1)) or {}
    return front_matter, match.group(2)
