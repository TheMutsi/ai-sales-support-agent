"""Integration tests for the retriever.

Require a real Postgres with pgvector (`alembic upgrade head`) — same reason as
the other RAG integration tests: pgvector's similarity operators only exist in
Postgres. Embeddings are stubbed with hand-picked orthogonal unit vectors so
similarity ranking is deterministic and assertable, instead of depending on what a
real embeddings model happens to consider "similar". The `rag_db` fixture (shared
with `test_rag_ingestion.py`) lives in `conftest.py`.
"""

from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk
from app.rag import retriever
from app.schemas.rag import DocType

_DIM = 768


class _FakeEmbeddings:
    def __init__(self, query_vector: list[float]):
        self._query_vector = query_vector

    def embed_query(self, text: str) -> list[float]:
        return self._query_vector


def _unit_vector(index: int) -> list[float]:
    """An orthogonal unit vector: cosine distance to itself is 0, to any other
    `_unit_vector(j != index)` is 1 — makes similarity ranking exact, not just
    approximately closer/farther."""
    vector = [0.0] * _DIM
    vector[index] = 1.0
    return vector


def _add_document(
    rag_db: Session,
    *,
    source: str,
    doc_type: DocType,
    chunks: list[tuple[str, list[float]]],
    plan_scope: str | None = None,
) -> Document:
    document = Document(title=source, doc_type=doc_type.value, source=source, content="x", plan_scope=plan_scope)
    rag_db.add(document)
    rag_db.flush()

    for index, (content, embedding) in enumerate(chunks):
        rag_db.add(
            DocumentChunk(
                document_id=document.id, chunk_index=index, content=content, embedding=embedding, chunk_metadata={}
            )
        )
    rag_db.commit()
    return document


def test_search_orders_by_similarity(rag_db: Session, monkeypatch):
    _add_document(
        rag_db,
        source="a.md",
        doc_type=DocType.POLICY,
        chunks=[("close", _unit_vector(0)), ("far", _unit_vector(1))],
    )
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    results = retriever.search(rag_db, "query", top_k=2)

    assert [r.content for r in results] == ["close", "far"]
    assert results[0].score > results[1].score


def test_search_respects_top_k(rag_db: Session, monkeypatch):
    _add_document(
        rag_db,
        source="a.md",
        doc_type=DocType.POLICY,
        chunks=[(f"c{i}", _unit_vector(i)) for i in range(5)],
    )
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    results = retriever.search(rag_db, "query", top_k=2)

    assert len(results) == 2


def test_search_filters_by_doc_type(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="policy.md", doc_type=DocType.POLICY, chunks=[("p", _unit_vector(0))])
    _add_document(rag_db, source="faq.md", doc_type=DocType.FAQ, chunks=[("f", _unit_vector(0))])
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    results = retriever.search(rag_db, "query", top_k=10, doc_type=DocType.FAQ)

    assert [r.content for r in results] == ["f"]


def test_search_drops_results_below_min_score(rag_db: Session, monkeypatch):
    _add_document(
        rag_db,
        source="a.md",
        doc_type=DocType.POLICY,
        chunks=[("close", _unit_vector(0)), ("far", _unit_vector(1))],
    )
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    # "close" has score 1.0 (identical vector), "far" has score 0.0 (orthogonal).
    results = retriever.search(rag_db, "query", top_k=2, min_score=0.5)

    assert [r.content for r in results] == ["close"]


def test_search_with_plan_scope_includes_unscoped_docs(rag_db: Session, monkeypatch):
    _add_document(
        rag_db, source="pro.md", doc_type=DocType.POLICY, plan_scope="pro", chunks=[("pro-only", _unit_vector(0))]
    )
    _add_document(
        rag_db, source="general.md", doc_type=DocType.POLICY, plan_scope=None, chunks=[("general", _unit_vector(0))]
    )
    _add_document(
        rag_db,
        source="starter.md",
        doc_type=DocType.POLICY,
        plan_scope="starter",
        chunks=[("starter-only", _unit_vector(0))],
    )
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    results = retriever.search(rag_db, "query", top_k=10, plan_scope="pro")

    assert {r.content for r in results} == {"pro-only", "general"}
