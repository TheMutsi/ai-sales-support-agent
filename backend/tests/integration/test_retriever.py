import uuid

from sqlalchemy.orm import Session

from app.db.models import Document, Tenant
from app.rag import retriever
from app.schemas.rag import DocType
from tests.integration.conftest import add_published_document, kb_test_tenant

_DIM = 768
_ANY_SIMILARITY = -1.0


class _FakeEmbeddings:
    def __init__(self, query_vector: list[float]):
        self._query_vector = query_vector

    def embed_query(self, text: str) -> list[float]:
        return self._query_vector


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * _DIM
    vector[index] = 1.0
    return vector


def _blend(first: int, second: int, weight: float) -> list[float]:
    vector = [0.0] * _DIM
    vector[first] = weight
    vector[second] = (1 - weight**2) ** 0.5
    return vector


def _add_document(
    rag_db: Session,
    *,
    source: str,
    doc_type: DocType = DocType.POLICY,
    chunks: list[tuple[str, list[float]]],
    plan_scope: str | None = None,
    section_titles: list[str | None] | None = None,
    tenant: Tenant | None = None,
) -> Document:
    return add_published_document(
        rag_db,
        source=source,
        doc_type=doc_type.value,
        plan_scope=plan_scope,
        chunks=chunks,
        section_titles=section_titles,
        tenant=tenant,
    )


def _search(rag_db: Session, monkeypatch, query_vector: list[float], query: str = "query", **kwargs):
    monkeypatch.setattr(retriever, "get_embeddings", lambda: _FakeEmbeddings(query_vector))
    return retriever.search(rag_db, query, tenant_id=kb_test_tenant(rag_db).id, **kwargs)


def test_search_orders_by_similarity(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="a.md", chunks=[("close", _unit_vector(0)), ("far", _unit_vector(1))])

    results = _search(rag_db, monkeypatch, _unit_vector(0), min_score=_ANY_SIMILARITY)

    assert [r.content for r in results] == ["close", "far"]
    assert results[0].score > results[1].score


def test_search_respects_top_k(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="a.md", chunks=[(f"c{i}", _unit_vector(i)) for i in range(5)])

    results = _search(rag_db, monkeypatch, _unit_vector(0), top_k=2, min_score=_ANY_SIMILARITY)

    assert len(results) == 2


def test_search_filters_by_doc_type(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="policy.md", doc_type=DocType.POLICY, chunks=[("p", _unit_vector(0))])
    _add_document(rag_db, source="faq.md", doc_type=DocType.FAQ, chunks=[("f", _unit_vector(0))])

    results = _search(rag_db, monkeypatch, _unit_vector(0), doc_type=DocType.FAQ)

    assert [r.content for r in results] == ["f"]


def test_search_drops_results_below_the_minimum_relevance(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="a.md", chunks=[("close", _unit_vector(0)), ("far", _unit_vector(1))])

    results = _search(rag_db, monkeypatch, _unit_vector(0), min_score=0.5)

    assert [r.content for r in results] == ["close"]


def test_search_says_nothing_when_nothing_is_relevant(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="a.md", chunks=[("far", _unit_vector(1))])

    assert _search(rag_db, monkeypatch, _unit_vector(0)) == []


def test_search_with_plan_scope_includes_unscoped_docs(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="pro.md", plan_scope="pro", chunks=[("pro-only", _unit_vector(0))])
    _add_document(rag_db, source="general.md", plan_scope=None, chunks=[("general", _unit_vector(0))])
    _add_document(rag_db, source="starter.md", plan_scope="starter", chunks=[("starter-only", _unit_vector(0))])

    results = _search(rag_db, monkeypatch, _unit_vector(0), top_k=10, plan_scope="pro")

    assert {r.content for r in results} == {"pro-only", "general"}


def test_search_without_a_plan_returns_only_unscoped_docs(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="pro.md", plan_scope="pro", chunks=[("pro-only", _unit_vector(0))])
    _add_document(rag_db, source="general.md", plan_scope=None, chunks=[("general", _unit_vector(0))])

    results = _search(rag_db, monkeypatch, _unit_vector(0), top_k=10)

    assert {r.content for r in results} == {"general"}


def test_search_results_carry_the_title_source_and_version(rag_db: Session, monkeypatch):
    _add_document(rag_db, source="policy/refunds.md", chunks=[("refund window", _unit_vector(0))])
    rag_db.query(Document).update({"title": "Refund policy"})
    rag_db.commit()

    [result] = _search(rag_db, monkeypatch, _unit_vector(0))

    assert (result.document_title, result.source, result.version) == ("Refund policy", "policy/refunds.md", 1)


def test_a_keyword_the_vector_misses_is_found_by_full_text(rag_db: Session, monkeypatch):
    _add_document(
        rag_db,
        source="terms.md",
        chunks=[("the indemnification clause limits liability", _unit_vector(5)), ("unrelated", _unit_vector(6))],
    )

    results = _search(rag_db, monkeypatch, _unit_vector(0), query="indemnification")

    assert [r.content for r in results] == ["the indemnification clause limits liability"]


def test_a_chunk_found_by_both_rankings_beats_one_found_by_the_vector_alone(rag_db: Session, monkeypatch):
    _add_document(
        rag_db,
        source="a.md",
        chunks=[("alpha", _unit_vector(0)), ("zebra stripes", _blend(0, 1, 0.8)), ("gamma", _unit_vector(2))],
    )

    results = _search(rag_db, monkeypatch, _unit_vector(0), query="zebra")

    assert [r.content for r in results] == ["zebra stripes", "alpha"]
    assert results[0].score > results[1].score


def test_a_hit_returns_its_whole_section_once(rag_db: Session, monkeypatch):
    _add_document(
        rag_db,
        source="faq.md",
        doc_type=DocType.FAQ,
        chunks=[("part one", _unit_vector(0)), ("part two", _unit_vector(0)), ("other", _unit_vector(1))],
        section_titles=["Refunds", "Refunds", "Billing"],
    )

    results = _search(rag_db, monkeypatch, _unit_vector(0))

    assert [(r.section, r.content) for r in results] == [("Refunds", "part one\n\npart two")]


def test_search_never_returns_another_tenants_documents(rag_db: Session, monkeypatch):
    other = Tenant(name="Other shop", api_key=f"pk_other_{uuid.uuid4().hex[:8]}")
    rag_db.add(other)
    rag_db.commit()
    try:
        _add_document(rag_db, source="mine.md", chunks=[("mine", _unit_vector(0))])
        _add_document(rag_db, source="theirs.md", chunks=[("theirs", _unit_vector(0))], tenant=other)

        results = _search(rag_db, monkeypatch, _unit_vector(0), top_k=10)

        assert [r.content for r in results] == ["mine"]
    finally:
        rag_db.query(Document).delete()
        rag_db.delete(other)
        rag_db.commit()


def test_search_skips_documents_without_a_published_version(rag_db: Session, monkeypatch):
    document = _add_document(rag_db, source="a.md", chunks=[("hidden", _unit_vector(0))])
    document.published_version_id = None
    rag_db.commit()

    assert _search(rag_db, monkeypatch, _unit_vector(0)) == []
