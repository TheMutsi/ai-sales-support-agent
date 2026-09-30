"""Integration tests for the RAG ingestion pipeline.

Require a real Postgres with the schema already migrated (`alembic upgrade head`)
against DATABASE_URL — pgvector's column type has no SQLite equivalent, so these
can't run against an in-memory database. Embeddings are stubbed with a fixed
768-dim vector per chunk so these tests don't depend on a live LLM/embeddings
provider being configured — real embedding *quality* is a concern for the
evaluation suite, not this test, which only checks that ingestion persists the
right rows with the right relationships. The `rag_db` fixture (shared with
`test_retriever.py`) lives in `conftest.py`.
"""

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
    assert rag_db.query(Document).count() == 2  # privacy-policy.md, terms-and-conditions.md


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

    assert rag_db.query(Document).count() == 2
    assert rag_db.query(DocumentChunk).count() == first_chunk_count
