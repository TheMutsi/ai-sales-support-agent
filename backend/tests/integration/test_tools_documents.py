import uuid

from sqlalchemy.orm import Session

from app.db.models import Document, Tenant
from app.rag.tokens import DOCUMENT_TOKEN_LIMIT
from app.tools.documents import CALL_TOKEN_LIMIT, open_documents
from tests.integration.conftest import add_published_document, kb_test_tenant


def _text_of_tokens(tokens: int) -> str:
    return "a" * (tokens * 3)


def test_opens_the_full_published_text(rag_db: Session):
    document = add_published_document(rag_db, source="a.md", chunks=[], content="full text", title="A")

    result = open_documents(kb_test_tenant(rag_db).id, None, [document.id])

    [opened] = result.documents
    assert (opened.title, opened.text, opened.version, opened.omitted_reason) == ("A", "full text", 1, None)
    assert (opened.doc_type, opened.source) == (document.doc_type, "a.md")
    assert result.not_found == []


def test_a_document_over_the_limit_returns_its_section_titles(rag_db: Session):
    content = "## Setup\n" + _text_of_tokens(DOCUMENT_TOKEN_LIMIT) + "\n## Limits\nmore"
    document = add_published_document(rag_db, source="big.md", chunks=[], content=content)

    [opened] = open_documents(kb_test_tenant(rag_db).id, None, [document.id]).documents

    assert opened.text is None
    assert opened.omitted_reason == "document_too_long"
    assert opened.section_titles == ["Setup", "Limits"]


def test_documents_past_the_call_limit_return_their_section_titles(rag_db: Session):
    body = _text_of_tokens(DOCUMENT_TOKEN_LIMIT - 100)
    documents = [
        add_published_document(rag_db, source=f"{i}.md", chunks=[], content=f"## Part {i}\n{body}")
        for i in range(3)
    ]
    ids = [document.id for document in documents]

    result = open_documents(kb_test_tenant(rag_db).id, None, ids)

    assert [opened.omitted_reason for opened in result.documents] == [None, None, "call_limit_reached"]
    assert result.documents[2].section_titles == ["Part 2"]
    assert sum(opened.estimated_tokens for opened in result.documents[:2]) <= CALL_TOKEN_LIMIT


def test_unknown_ids_are_reported_not_raised(rag_db: Session):
    document = add_published_document(rag_db, source="a.md", chunks=[], content="text")
    unknown = uuid.uuid4()

    result = open_documents(kb_test_tenant(rag_db).id, None, [unknown, document.id, document.id])

    assert result.not_found == [unknown]
    assert [opened.document_id for opened in result.documents] == [document.id]


def test_another_tenants_document_is_not_found(rag_db: Session):
    other = Tenant(name="Other shop", api_key=f"pk_other_{uuid.uuid4().hex[:8]}")
    rag_db.add(other)
    rag_db.commit()
    try:
        theirs = add_published_document(rag_db, source="theirs.md", chunks=[], tenant=other)

        result = open_documents(kb_test_tenant(rag_db).id, None, [theirs.id])

        assert result.documents == []
        assert result.not_found == [theirs.id]
    finally:
        rag_db.query(Document).delete()
        rag_db.delete(other)
        rag_db.commit()


def test_a_document_of_another_plan_is_not_found(rag_db: Session):
    starter = add_published_document(rag_db, source="s.md", chunks=[], plan_scope="starter")
    general = add_published_document(rag_db, source="g.md", chunks=[], plan_scope=None)

    result = open_documents(kb_test_tenant(rag_db).id, "pro", [starter.id, general.id])

    assert result.not_found == [starter.id]
    assert [opened.document_id for opened in result.documents] == [general.id]


def test_without_a_plan_only_unscoped_documents_open(rag_db: Session):
    starter = add_published_document(rag_db, source="s.md", chunks=[], plan_scope="starter")
    general = add_published_document(rag_db, source="g.md", chunks=[], plan_scope=None)

    result = open_documents(kb_test_tenant(rag_db).id, None, [starter.id, general.id])

    assert result.not_found == [starter.id]
    assert [opened.document_id for opened in result.documents] == [general.id]


def test_an_unpublished_document_is_not_found(rag_db: Session):
    document = add_published_document(rag_db, source="a.md", chunks=[])
    document.published_version_id = None
    rag_db.commit()

    assert open_documents(kb_test_tenant(rag_db).id, None, [document.id]).not_found == [document.id]
