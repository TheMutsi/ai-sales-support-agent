import pytest
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk
from app.rag import ingestion


class _FakeEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    monkeypatch.setattr(ingestion, "get_embeddings", lambda: _FakeEmbeddings())


def test_ingest_persists_documents_and_chunks(rag_db: Session):
    written = ingestion.ingest(rag_db)

    assert written == rag_db.query(DocumentChunk).count()
    assert rag_db.query(Document).count() == 7


def test_ingest_links_chunks_to_their_document(rag_db: Session):
    ingestion.ingest(rag_db)

    privacy = rag_db.query(Document).filter_by(source="privacy-policy.md").one()
    assert len(privacy.chunks) > 0
    assert all(chunk.document_id == privacy.id for chunk in privacy.chunks)
    assert all(len(chunk.embedding) == 768 for chunk in privacy.chunks)


def test_ingest_is_idempotent_on_source(rag_db: Session):
    ingestion.ingest(rag_db)
    first_chunk_count = rag_db.query(DocumentChunk).count()

    ingestion.ingest(rag_db)

    assert rag_db.query(Document).count() == 7
    assert rag_db.query(DocumentChunk).count() == first_chunk_count
