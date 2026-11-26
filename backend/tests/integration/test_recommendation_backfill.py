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
from app.recommendations.backfill import backfill_tag
from app.schemas.recommendations import TagFit


def _vector(*leading: float) -> list[float]:
    return [*leading, *([0.0] * (EMBEDDING_DIM - len(leading)))]


class _FakeEmbeddings:
    def embed_query(self, text: str) -> list[float]:
        return _vector(1.0)


class _FakeStructured:
    def __init__(self, decide):
        self._decide = decide

    def with_retry(self, **_):
        return self

    def invoke(self, messages):
        return self._decide(messages[-1].content)


class _FakeLLM:
    def __init__(self, decide):
        self._decide = decide

    def with_structured_output(self, _schema):
        return _FakeStructured(self._decide)


def _applies_when(word: str):
    def decide(prompt: str) -> TagFit:
        if "boom" in prompt:
            raise RuntimeError("model is down")
        if word in prompt:
            return TagFit(applies=True, weight=0.8, why="stated")
        return TagFit(applies=False)

    return decide


@pytest.fixture
def shop(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        item_type = RecommendationType(tenant_id=tenant.id, key="p", name="P", card_template="product_card")
        db.add(item_type)
        db.flush()
        new_tag = RecommendationTag(tenant_id=tenant.id, slug="calming", description="Calms skin", embedding=_vector(1.0))
        near_tag = RecommendationTag(tenant_id=tenant.id, slug="soothing", description="Soothes", embedding=_vector(0.9, 0.1))
        far_tag = RecommendationTag(tenant_id=tenant.id, slug="vegan", description="Vegan", embedding=_vector(0.0, 0.0, 1.0))
        db.add_all([new_tag, near_tag, far_tag])
        db.flush()

        def add_item(external_id, desc, embedding, tag=None, status="active"):
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
            if tag is not None:
                db.add(ItemTag(item_id=item.id, tag_id=tag.id, tenant_id=tenant.id, weight=0.5))
            return item

        add_item("holds-near-tag", "calms redness", _vector(0.0, 1.0), near_tag)
        add_item("close-by-embedding", "calms and heals", _vector(0.95, 0.05))
        add_item("unrelated", "plain soap", _vector(0.0, 0.0, 0.0, 1.0), far_tag)
        add_item("archived", "calms everything", _vector(1.0), status="archived")
        db.commit()
        yield db, tenant.id, new_tag.id


def _tagged(db, tag_id):
    rows = db.query(RecommendationItem.external_id).join(ItemTag, ItemTag.item_id == RecommendationItem.id)
    return {external_id for (external_id,) in rows.filter(ItemTag.tag_id == tag_id)}


def test_only_candidate_items_that_fit_get_the_new_tag(shop):
    db, tenant_id, tag_id = shop

    result = backfill_tag(db, tenant_id, tag_id, llm=_FakeLLM(_applies_when("calms")), embeddings=_FakeEmbeddings())

    assert _tagged(db, tag_id) == {"holds-near-tag", "close-by-embedding"}
    assert set(result.tagged) == {"holds-near-tag", "close-by-embedding"}


def test_archived_items_are_not_candidates(shop):
    db, tenant_id, tag_id = shop

    backfill_tag(db, tenant_id, tag_id, llm=_FakeLLM(_applies_when("calms")), embeddings=_FakeEmbeddings())

    assert "archived" not in _tagged(db, tag_id)


def test_a_backfill_never_creates_tags(shop):
    db, tenant_id, tag_id = shop
    before = db.query(RecommendationTag).filter_by(tenant_id=tenant_id).count()

    backfill_tag(db, tenant_id, tag_id, llm=_FakeLLM(_applies_when("calms")), embeddings=_FakeEmbeddings())

    assert db.query(RecommendationTag).filter_by(tenant_id=tenant_id).count() == before


def test_existing_tags_of_the_checked_items_are_untouched(shop):
    db, tenant_id, tag_id = shop

    backfill_tag(db, tenant_id, tag_id, llm=_FakeLLM(_applies_when("calms")), embeddings=_FakeEmbeddings())

    near = db.query(RecommendationTag).filter_by(tenant_id=tenant_id, slug="soothing").one()
    assert _tagged(db, near.id) == {"holds-near-tag"}


def test_running_it_twice_does_not_duplicate_links(shop):
    db, tenant_id, tag_id = shop
    llm = _FakeLLM(_applies_when("calms"))

    backfill_tag(db, tenant_id, tag_id, llm=llm, embeddings=_FakeEmbeddings())
    second = backfill_tag(db, tenant_id, tag_id, llm=llm, embeddings=_FakeEmbeddings())

    assert second.tagged == []
    assert db.query(ItemTag).filter_by(tag_id=tag_id).count() == 2


def test_a_failing_item_is_reported_and_the_others_continue(shop):
    db, tenant_id, tag_id = shop
    item = db.query(RecommendationItem).filter_by(external_id="holds-near-tag").one()
    item.short_desc = "boom calms"
    db.commit()

    result = backfill_tag(db, tenant_id, tag_id, llm=_FakeLLM(_applies_when("calms")), embeddings=_FakeEmbeddings())

    assert result.failed == ["holds-near-tag"]
    assert "close-by-embedding" in result.tagged
