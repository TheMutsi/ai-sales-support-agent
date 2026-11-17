import uuid

from sqlalchemy.orm import Session

from app.rag import retriever
from app.schemas.rag import DocType
from app.tools.knowledge_base import current_plan_slug, search_knowledge_base
from tests.integration.conftest import add_published_document, customer_by_email, kb_test_tenant

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
    add_published_document(
        rag_db, source=source, doc_type=DocType.FEATURES.value, plan_scope=plan_scope, chunks=[(content, _unit_vector(0))]
    )


def test_scopes_search_to_the_customers_plan(seeded_db: Session, rag_db: Session, monkeypatch):
    _add_document(rag_db, source="pro.md", plan_scope="pro", content="pro-only")
    _add_document(rag_db, source="starter.md", plan_scope="starter", content="starter-only")
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    results = search_knowledge_base("query", tenant_id=kb_test_tenant(rag_db).id, plan_slug="pro")

    assert [r.content for r in results] == ["pro-only"]


def test_searches_unscoped_for_customer_without_a_subscription(
    seeded_db: Session, rag_db: Session, monkeypatch
):
    _add_document(rag_db, source="general.md", plan_scope=None, content="general")
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    results = search_knowledge_base("query", tenant_id=kb_test_tenant(rag_db).id, plan_slug=None)

    assert [r.content for r in results] == ["general"]


def test_finds_nothing_in_another_tenants_knowledge_base(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="general.md", plan_scope=None, content="general")
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(_unit_vector(0)))

    assert search_knowledge_base("query", tenant_id=uuid.uuid4(), plan_slug=None) == []


def test_the_plan_slug_is_the_customers_current_plan(seeded_db: Session):
    customer = customer_by_email(seeded_db, "priya.anand@bluecrestlogistics.com")

    assert current_plan_slug(customer.id) == "pro"


def test_the_plan_slug_is_none_without_a_customer_or_a_subscription():
    assert current_plan_slug(None) is None
    assert current_plan_slug(uuid.uuid4()) is None
