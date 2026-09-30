"""Unit tests for the KB loader.

Front-matter parsing is deterministic (file in, `SourceDocument` out, or a raise),
so it's tested the same way as the provider factories: pure input/output, no
network or DB needed. Each test writes its own throwaway `.md` files under
pytest's `tmp_path`, instead of depending on the real seed KB in
`backend/data/seed/kb/` — that keeps these tests correct even if the seed content
changes later.
"""

import pytest

from app.rag.loaders import load_documents
from app.schemas.rag import DocType


def _write(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_loads_document_with_full_front_matter(tmp_path):
    _write(
        tmp_path / "refunds.md",
        '---\ntitle: "Refund Policy"\ndoc_type: policy\nproduct_area: legal\n'
        'plan_scope: pro\nversion: "2.0"\n---\nRefunds are issued within 14 days.\n',
    )

    documents = load_documents(kb_dir=tmp_path)

    assert len(documents) == 1
    document = documents[0]
    assert document.title == "Refund Policy"
    assert document.doc_type == DocType.POLICY
    assert document.product_area == "legal"
    assert document.plan_scope == "pro"
    assert document.version == "2.0"
    assert document.source == "refunds.md"
    assert document.content == "Refunds are issued within 14 days."


def test_defaults_version_and_optional_fields_when_omitted(tmp_path):
    _write(tmp_path / "faq.md", '---\ntitle: "FAQ"\ndoc_type: faq\n---\nSome content.\n')

    document = load_documents(kb_dir=tmp_path)[0]

    assert document.version == "1.0"
    assert document.product_area is None
    assert document.plan_scope is None


def test_source_is_relative_to_kb_dir(tmp_path):
    nested = tmp_path / "policy"
    nested.mkdir()
    _write(nested / "refunds.md", '---\ntitle: "Refund Policy"\ndoc_type: policy\n---\nContent.\n')

    document = load_documents(kb_dir=tmp_path)[0]

    assert document.source == "policy/refunds.md"


def test_raises_on_missing_front_matter_block(tmp_path):
    _write(tmp_path / "broken.md", "# No front matter here\nJust content.\n")

    with pytest.raises(ValueError, match="missing YAML front-matter block"):
        load_documents(kb_dir=tmp_path)


def test_raises_on_missing_required_field(tmp_path):
    _write(tmp_path / "broken.md", '---\ntitle: "Missing doc_type"\n---\nContent.\n')

    with pytest.raises(ValueError, match="missing required front-matter field"):
        load_documents(kb_dir=tmp_path)


def test_raises_on_unsupported_doc_type(tmp_path):
    _write(tmp_path / "broken.md", '---\ntitle: "Bad Type"\ndoc_type: pricing\n---\nContent.\n')

    with pytest.raises(ValueError, match="not a valid DocType"):
        load_documents(kb_dir=tmp_path)


def test_loads_real_seed_kb_documents():
    """Sanity check against the actual KB content, not just synthetic fixtures —
    catches the case where a real seed doc's front-matter drifts out of sync with
    what the loader expects."""
    from app.rag.loaders import KB_DIR

    documents = load_documents(kb_dir=KB_DIR)

    assert {d.source for d in documents} == {"privacy-policy.md", "terms-and-conditions.md"}
    assert all(d.doc_type == DocType.POLICY for d in documents)
