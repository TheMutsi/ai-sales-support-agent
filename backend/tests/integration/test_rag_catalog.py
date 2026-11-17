from sqlalchemy.orm import Session

from app.rag import catalog
from app.rag.tokens import estimate_tokens
from tests.integration.conftest import add_published_document, kb_test_tenant


def test_the_map_lists_published_documents_ordered_by_id(rag_db: Session):
    first = add_published_document(rag_db, source="a.md", chunks=[], content="abc" * 10, title="A")
    second = add_published_document(rag_db, source="b.md", chunks=[], content="def", title="B", plan_scope="pro")
    unpublished = add_published_document(rag_db, source="c.md", chunks=[], title="C")
    unpublished.published_version_id = None
    rag_db.commit()
    tenant_id = kb_test_tenant(rag_db).id

    entries = catalog.load_published_document_map(tenant_id)

    expected = sorted([first, second], key=lambda document: document.id)
    assert [entry.document_id for entry in entries] == [document.id for document in expected]
    by_title = {entry.title: entry for entry in entries}
    assert by_title["A"].estimated_tokens == estimate_tokens("abc" * 10)
    assert by_title["B"].plan_scope == "pro"
    assert by_title["B"].when_to_use == "test"


def test_invalidate_makes_a_new_publication_visible(rag_db: Session):
    tenant_id = kb_test_tenant(rag_db).id
    catalog.document_catalog.clear()
    assert catalog.get_document_map(tenant_id) == ()

    add_published_document(rag_db, source="a.md", chunks=[], title="A")
    assert catalog.get_document_map(tenant_id) == ()

    catalog.invalidate(tenant_id)

    assert [entry.title for entry in catalog.get_document_map(tenant_id)] == ["A"]
    catalog.document_catalog.clear()
