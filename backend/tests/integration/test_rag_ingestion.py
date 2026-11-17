import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk, DocumentVersion, Tenant
from app.rag import ingestion, retriever
from tests.integration.conftest import add_published_document, kb_test_tenant


class _FakeEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]


class _FailingEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding provider is down")


class _QueryEmbeddings:
    def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 767


def _document_with_published_version(rag_db: Session, tenant: Tenant, source: str = "faq.md") -> Document:
    return add_published_document(rag_db, source=source, tenant=tenant, chunks=[("old", [1.0] + [0.0] * 767)])


def test_ingest_loads_the_seed_documents_as_published_version_one(rag_db: Session):
    tenant = kb_test_tenant(rag_db)

    written = ingestion.ingest(rag_db, tenant.id, _FakeEmbeddings())

    documents = rag_db.query(Document).filter_by(tenant_id=tenant.id).all()
    assert len(documents) == 7
    assert written == rag_db.query(DocumentChunk).count() > 0
    for document in documents:
        version = rag_db.get(DocumentVersion, document.published_version_id)
        assert (version.version, version.status, version.published_by) == (1, "published", "seed")
        assert document.when_to_use
        assert all(chunk.document_version_id == version.id for chunk in version.chunks)
        assert all(len(chunk.embedding) == 768 for chunk in version.chunks)


def test_ingested_chunks_have_their_search_vector_filled(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    ingestion.ingest(rag_db, tenant.id, _FakeEmbeddings())

    unfilled = rag_db.execute(text("SELECT count(*) FROM document_chunks WHERE content_tsv IS NULL")).scalar()

    assert unfilled == 0


def test_ingest_twice_keeps_one_version_per_document(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    ingestion.ingest(rag_db, tenant.id, _FakeEmbeddings())
    first_chunk_count = rag_db.query(DocumentChunk).count()

    assert ingestion.ingest(rag_db, tenant.id, _FakeEmbeddings()) == 0

    assert rag_db.query(Document).count() == 7
    assert rag_db.query(DocumentVersion).count() == 7
    assert rag_db.query(DocumentChunk).count() == first_chunk_count


def test_ingest_archives_sources_no_longer_on_disk(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    gone = _document_with_published_version(rag_db, tenant, source="removed.md")
    gone.origin = "seed"
    rag_db.commit()

    ingestion.ingest(rag_db, tenant.id, _FakeEmbeddings())

    rag_db.refresh(gone)
    assert gone.published_version_id is None
    assert gone.versions[0].status == "archived"


def test_ingest_leaves_a_back_office_document_serving(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    admin_document = _document_with_published_version(rag_db, tenant, source="admin/6f1c")

    ingestion.ingest(rag_db, tenant.id, _FakeEmbeddings())

    rag_db.refresh(admin_document)
    assert admin_document.origin == "admin"
    assert admin_document.published_version_id is not None
    assert rag_db.query(DocumentChunk).filter_by(document_version_id=admin_document.published_version_id).count() == 1


def test_ingested_documents_have_the_seed_origin(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    ingestion.ingest(rag_db, tenant.id, _FakeEmbeddings())
    assert {d.origin for d in rag_db.query(Document).filter_by(tenant_id=tenant.id)} == {"seed"}


def test_publishing_flips_the_document_and_archives_the_previous_version(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    document = _document_with_published_version(rag_db, tenant)
    previous_id = document.published_version_id
    draft = ingestion.create_draft_version(rag_db, document, "# New\n\nNew content.")
    rag_db.commit()

    written = ingestion.publish_version(rag_db, draft.id, _FakeEmbeddings(), "ana")

    rag_db.refresh(document)
    assert document.published_version_id == draft.id
    assert rag_db.get(DocumentVersion, previous_id).status == "archived"
    assert (draft.version, draft.status, draft.published_by) == (2, "published", "ana")
    assert draft.published_at is not None
    assert written == len(draft.chunks) > 0
    assert rag_db.query(DocumentChunk).filter_by(document_version_id=previous_id).count() == 0


def test_publish_version_does_not_commit(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    document = _document_with_published_version(rag_db, tenant)
    previous_id = document.published_version_id
    draft = ingestion.create_draft_version(rag_db, document, "# New\n\nNew content.")
    rag_db.commit()

    ingestion.publish_version(rag_db, draft.id, _FakeEmbeddings(), "ana")
    rag_db.rollback()

    rag_db.refresh(document)
    assert document.published_version_id == previous_id
    assert rag_db.query(DocumentChunk).filter_by(document_version_id=draft.id).count() == 0
    assert rag_db.query(DocumentChunk).filter_by(document_version_id=previous_id).count() == 1


def test_a_failed_embedding_leaves_the_previous_version_serving(rag_db: Session):
    tenant = kb_test_tenant(rag_db)
    document = _document_with_published_version(rag_db, tenant)
    previous_id = document.published_version_id
    draft = ingestion.create_draft_version(rag_db, document, "# New\n\nNew content.")
    rag_db.commit()

    with pytest.raises(ingestion.EmbeddingError) as raised:
        ingestion.publish_version(rag_db, draft.id, _FailingEmbeddings(), "ana")
    assert isinstance(raised.value.__cause__, RuntimeError)

    rag_db.rollback()
    rag_db.refresh(document)
    assert document.published_version_id == previous_id
    assert rag_db.get(DocumentVersion, previous_id).status == "published"
    assert rag_db.get(DocumentVersion, draft.id).status == "draft"
    assert rag_db.query(DocumentChunk).filter_by(document_version_id=draft.id).count() == 0


def test_publishing_an_unknown_version_fails(rag_db: Session):
    with pytest.raises(LookupError):
        ingestion.publish_version(rag_db, uuid.uuid4(), _FakeEmbeddings(), "ana")


def test_the_retriever_serves_only_the_published_version(rag_db: Session, monkeypatch):
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _QueryEmbeddings())
    tenant = kb_test_tenant(rag_db)
    document = _document_with_published_version(rag_db, tenant)
    draft = ingestion.create_draft_version(rag_db, document, "# New\n\nNew content.")
    rag_db.commit()
    assert [r.content for r in retriever.search(rag_db, "q", tenant_id=tenant.id)] == ["old"]

    ingestion.publish_version(rag_db, draft.id, _FakeEmbeddings(), "ana")

    assert "old" not in [r.content for r in retriever.search(rag_db, "q", tenant_id=tenant.id)]


def test_documents_are_isolated_per_tenant(rag_db: Session, monkeypatch):
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _QueryEmbeddings())
    tenant = kb_test_tenant(rag_db)
    other = Tenant(name="Other shop", api_key="pk_kb_other")
    rag_db.add(other)
    rag_db.commit()
    try:
        add_published_document(rag_db, source="faq.md", tenant=tenant, chunks=[("mine", [1.0] + [0.0] * 767)])
        add_published_document(rag_db, source="faq.md", tenant=other, chunks=[("theirs", [1.0] + [0.0] * 767)])

        assert [r.content for r in retriever.search(rag_db, "q", tenant_id=tenant.id)] == ["mine"]
        assert [r.content for r in retriever.search(rag_db, "q", tenant_id=other.id)] == ["theirs"]
        assert rag_db.query(Document).filter_by(source="faq.md").count() == 2
    finally:
        rag_db.query(DocumentChunk).delete()
        rag_db.query(DocumentVersion).delete()
        rag_db.query(Document).delete()
        rag_db.delete(other)
        rag_db.commit()
