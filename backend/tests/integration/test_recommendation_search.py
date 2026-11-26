import pytest

from app.auth.credentials import generate_api_key
from app.db.models import (
    EMBEDDING_DIM,
    ItemTag,
    RecommendationItem,
    RecommendationTag,
    RecommendationType,
    Tenant,
)
from app.db.session import SessionLocal
from app.recommendations.search import search_items
from app.schemas.recommendations import TagSelection


def _vector(*leading: float) -> list[float]:
    return [*leading, *([0.0] * (EMBEDDING_DIM - len(leading)))]


class _FakeEmbeddings:
    def __init__(self, by_text: dict[str, list[float]] | None = None):
        self._by_text = by_text or {}

    def embed_query(self, text: str) -> list[float]:
        return self._by_text.get(text, _vector(0.0, 1.0))


class _FakeStructured:
    def __init__(self, result):
        self._result = result

    def with_retry(self, **_):
        return self

    def invoke(self, _messages):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeLLM:
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, _schema):
        return _FakeStructured(self._result)


@pytest.fixture
def shop(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        item_type = RecommendationType(tenant_id=tenant.id, key="p", name="P", card_template="product_card")
        db.add(item_type)
        db.flush()
        tags = {
            slug: RecommendationTag(tenant_id=tenant.id, slug=slug, description=slug)
            for slug in ("firming", "dry-skin", "vegan")
        }
        db.add_all(tags.values())
        db.flush()

        def add_item(external_id, desc, embedding, links, status="active"):
            item = RecommendationItem(
                tenant_id=tenant.id,
                type_id=item_type.id,
                external_id=external_id,
                title=external_id,
                short_desc=desc,
                price_cents=1000,
                status=status,
                embedding=embedding,
            )
            db.add(item)
            db.flush()
            for slug, weight, complement in links:
                db.add(
                    ItemTag(
                        item_id=item.id,
                        tag_id=tags[slug].id,
                        tenant_id=tenant.id,
                        weight=weight,
                        is_complement=complement,
                    )
                )
            return item

        ids = {
            "strong": add_item("strong", "a serum", _vector(1.0), [("firming", 0.9, False), ("dry-skin", 0.8, False)]),
            "partial": add_item("partial", "a cream", _vector(1.0), [("firming", 0.6, False)]),
            "weak": add_item("weak", "a mask", _vector(1.0), [("firming", 0.1, False)]),
            "archived": add_item("archived", "old", _vector(1.0), [("firming", 1.0, False)], status="archived"),
            "complement-only": add_item("complement-only", "a spf", _vector(1.0), [("firming", 1.0, True)]),
            "plain": add_item("plain", "lavender soap bar", _vector(0.0, 1.0), []),
        }
        db.commit()
        yield db, tenant.id, {name: str(item.id) for name, item in ids.items()}


def _llm(*slugs):
    return _FakeLLM(TagSelection(slugs=list(slugs)))


def test_items_are_ranked_by_matched_tag_weights(shop):
    db, tenant_id, ids = shop

    hits = search_items(db, tenant_id, "firming for dry skin", llm=_llm("firming", "dry-skin"), embeddings=_FakeEmbeddings())

    assert [hit.item_id for hit in hits] == [ids["strong"]]
    assert hits[0].source == "tags"


def test_the_relative_cut_drops_items_far_below_the_best(shop):
    db, tenant_id, ids = shop

    hits = search_items(db, tenant_id, "firming", llm=_llm("firming"), embeddings=_FakeEmbeddings())

    assert [hit.item_id for hit in hits] == [ids["strong"], ids["partial"]]


def test_archived_and_complement_only_items_are_not_returned_by_tags(shop):
    db, tenant_id, ids = shop

    hits = search_items(db, tenant_id, "firming", llm=_llm("firming"), embeddings=_FakeEmbeddings())

    assert ids["archived"] not in {hit.item_id for hit in hits}
    assert ids["complement-only"] not in {hit.item_id for hit in hits}


def test_invented_slugs_are_ignored_and_the_text_search_takes_over(shop):
    db, tenant_id, ids = shop

    hits = search_items(db, tenant_id, "lavender soap", llm=_llm("made-up"), embeddings=_FakeEmbeddings())

    assert hits[0].item_id == ids["plain"]
    assert hits[0].source == "hybrid"


def test_a_weak_tag_match_falls_back_to_the_text_search(shop):
    db, tenant_id, ids = shop

    hits = search_items(db, tenant_id, "lavender soap", llm=_llm("vegan"), embeddings=_FakeEmbeddings())

    assert hits[0].item_id == ids["plain"]
    assert hits[0].source == "hybrid"


def test_a_failing_model_falls_back_to_the_text_search(shop):
    db, tenant_id, ids = shop

    hits = search_items(
        db, tenant_id, "lavender soap", llm=_FakeLLM(RuntimeError("down")), embeddings=_FakeEmbeddings()
    )

    assert hits[0].item_id == ids["plain"]
    assert hits[0].source == "hybrid"


def test_other_tenants_items_are_never_returned(shop):
    db, _, _ = shop
    other = Tenant(name="Other", api_key=generate_api_key())
    db.add(other)
    db.commit()

    hits = search_items(db, other.id, "firming", llm=_llm("firming"), embeddings=_FakeEmbeddings())

    assert hits == []


def test_the_fallback_returns_nothing_when_no_item_is_close_or_matches_the_words(shop):
    db, tenant_id, _ = shop
    embeddings = _FakeEmbeddings({"asdf qwer": _vector(0.0, 0.0, 1.0)})

    hits = search_items(db, tenant_id, "asdf qwer", llm=_llm(), embeddings=embeddings)

    assert hits == []
