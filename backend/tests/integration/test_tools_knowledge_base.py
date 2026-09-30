"""Integration tests for the search_knowledge_base tool.

Combines `seeded_db` (real customers/plans/subscriptions) with `rag_db` (KB
documents), both from conftest.py. This tool's only real behavior beyond
`retriever.search()` itself is resolving a customer_id into a `plan_scope` —
these tests exist to prove that resolution actually happens, not to
re-verify similarity search (already covered by `test_retriever.py`).
Embeddings are stubbed the same way `test_retriever.py` stubs them, for the
same reason: deterministic ranking instead of depending on a real model.
"""

import uuid

from sqlalchemy.orm import Session

from app.db.models import Customer, Document, DocumentChunk
from app.rag import retriever
from app.schemas.rag import DocType
from app.tools.knowledge_base import search_knowledge_base

_DIM = 768


class _FakeEmbeddings:
    def __init__(self, query_vector: list[float]):
        self._query_vector = query_vector

    def embed_query(self, text: str) -> list[float]:
        return self._query_vector


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * _DIM
    vector[index] = 1.0
    return vector


def _add_document(rag_db: Session, *, source: str, plan_scope: str | None, content: str) -> None:
    document = Document(
        title=source,
        doc_type=DocType.FEATURES.value,
        source=source,
        content="x",
        plan_scope=plan_scope,
    )
    rag_db.add(document)
    rag_db.flush()
    rag_db.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content=content,
            embedding=_unit_vector(0),
            chunk_metadata={},
        )
    )
    rag_db.commit()


def test_scopes_search_to_the_customers_plan(seeded_db: Session, rag_db: Session, monkeypatch):
    _add_document(rag_db, source="pro.md", plan_scope="pro", content="pro-only")
    _add_document(rag_db, source="starter.md", plan_scope="starter", content="starter-only")
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    customer = (
        seeded_db.query(Customer).filter_by(email="priya.anand@bluecrestlogistics.com").one()
    )  # pro plan

    results = search_knowledge_base(customer.id, "query")

    assert [r.content for r in results] == ["pro-only"]


def test_searches_unscoped_for_customer_without_a_subscription(
    seeded_db: Session, rag_db: Session, monkeypatch
):
    _add_document(rag_db, source="general.md", plan_scope=None, content="general")
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    results = search_knowledge_base(uuid.uuid4(), "query")

    assert [r.content for r in results] == ["general"]
