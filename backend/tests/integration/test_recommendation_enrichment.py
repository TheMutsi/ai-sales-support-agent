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
from app.recommendations.enrichment import enrich_item
from app.schemas.recommendations import ItemEnrichment, TagAssignment


def _vector(*leading: float) -> list[float]:
    return [*leading, *([0.0] * (EMBEDDING_DIM - len(leading)))]


class _FakeEmbeddings:
    def __init__(self, by_text: dict[str, list[float]] | None = None):
        self._by_text = by_text or {}

    def embed_query(self, text: str) -> list[float]:
        return self._by_text.get(text, _vector(0.0, 0.0, 1.0))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


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
        item_type = RecommendationType(
            tenant_id=tenant.id, key="product", name="Product", card_template="product_card"
        )
        db.add(item_type)
        db.flush()
        item = RecommendationItem(
            tenant_id=tenant.id,
            type_id=item_type.id,
            external_id="sku-1",
            title="Firming serum",
            short_desc="Firms dry skin",
            price_cents=2500,
        )
        firming = RecommendationTag(
            tenant_id=tenant.id, slug="firming", description="Makes skin firmer", embedding=_vector(1.0)
        )
        db.add_all([item, firming])
        db.commit()
        yield db, tenant.id, item.id


def _tags_of(db, item_id):
    rows = db.query(ItemTag, RecommendationTag).join(RecommendationTag, RecommendationTag.id == ItemTag.tag_id)
    return {tag.slug: link for link, tag in rows.filter(ItemTag.item_id == item_id)}


def test_registry_tags_are_reused_and_weights_stored(shop):
    db, tenant_id, item_id = shop
    llm = _FakeLLM(ItemEnrichment(tags=[TagAssignment(slug="firming", weight=0.9, why="firms dry skin")]))

    result = enrich_item(db, tenant_id, item_id, llm=llm, embeddings=_FakeEmbeddings())

    assert result.status == "ready"
    assert result.reused_tags == ["firming"]
    assert result.created_tags == []
    assert _tags_of(db, item_id)["firming"].weight == 0.9
    assert db.get(RecommendationItem, item_id).enrichment_status == "ready"
    assert db.get(RecommendationItem, item_id).embedding is not None


def test_a_new_precise_tag_is_created_alongside_the_partly_fitting_one(shop):
    db, tenant_id, item_id = shop
    llm = _FakeLLM(
        ItemEnrichment(
            tags=[
                TagAssignment(slug="firming", weight=0.4, why="firms"),
                TagAssignment(slug="Dry Skin", description="Helps dry skin", weight=0.9, why="for dry skin"),
            ]
        )
    )

    result = enrich_item(db, tenant_id, item_id, llm=llm, embeddings=_FakeEmbeddings())

    assert result.created_tags == ["dry-skin"]
    assert set(_tags_of(db, item_id)) == {"firming", "dry-skin"}


def test_a_new_tag_that_is_a_near_duplicate_reuses_the_registry_tag(shop):
    db, tenant_id, item_id = shop
    embeddings = _FakeEmbeddings({"Tightens the skin": _vector(0.99, 0.05)})
    llm = _FakeLLM(
        ItemEnrichment(tags=[TagAssignment(slug="tightening", description="Tightens the skin", weight=0.8)])
    )

    result = enrich_item(db, tenant_id, item_id, llm=llm, embeddings=embeddings)

    assert result.created_tags == []
    assert list(_tags_of(db, item_id)) == ["firming"]
    assert db.query(RecommendationTag).filter_by(tenant_id=tenant_id).count() == 1


def test_complement_tags_are_marked(shop):
    db, tenant_id, item_id = shop
    llm = _FakeLLM(
        ItemEnrichment(
            tags=[TagAssignment(slug="firming", weight=0.9)],
            complement_tags=[TagAssignment(slug="sun-protection", description="Protects from sun", weight=0.7)],
        )
    )

    enrich_item(db, tenant_id, item_id, llm=llm, embeddings=_FakeEmbeddings())

    links = _tags_of(db, item_id)
    assert links["sun-protection"].is_complement is True
    assert links["firming"].is_complement is False


def test_pinned_tags_survive_and_other_old_tags_are_replaced(shop):
    db, tenant_id, item_id = shop
    old = RecommendationTag(tenant_id=tenant_id, slug="old", description="Old", embedding=_vector(0.0, 1.0))
    pinned = RecommendationTag(tenant_id=tenant_id, slug="vegan", description="Vegan", embedding=_vector(0.0, 0.0, 0.0, 1.0))
    db.add_all([old, pinned])
    db.flush()
    firming = db.query(RecommendationTag).filter_by(tenant_id=tenant_id, slug="firming").one()
    db.add_all(
        [
            ItemTag(item_id=item_id, tag_id=old.id, tenant_id=tenant_id, weight=0.5),
            ItemTag(item_id=item_id, tag_id=pinned.id, tenant_id=tenant_id, weight=1.0, pinned=True),
            ItemTag(item_id=item_id, tag_id=firming.id, tenant_id=tenant_id, weight=0.1),
        ]
    )
    db.commit()
    llm = _FakeLLM(
        ItemEnrichment(tags=[TagAssignment(slug="vegan", weight=0.2), TagAssignment(slug="firming", weight=0.9)])
    )

    enrich_item(db, tenant_id, item_id, llm=llm, embeddings=_FakeEmbeddings())

    links = _tags_of(db, item_id)
    assert set(links) == {"vegan", "firming"}
    assert links["vegan"].weight == 1.0 and links["vegan"].pinned is True
    assert links["firming"].weight == 0.9


def test_a_failing_model_marks_the_item_failed_and_changes_no_tags(shop):
    db, tenant_id, item_id = shop
    llm = _FakeLLM(RuntimeError("model is down"))

    result = enrich_item(db, tenant_id, item_id, llm=llm, embeddings=_FakeEmbeddings())

    assert result.status == "failed"
    assert "model is down" in result.error
    assert db.get(RecommendationItem, item_id).enrichment_status == "failed"
    assert _tags_of(db, item_id) == {}


def test_an_item_of_another_tenant_cannot_be_enriched(shop):
    db, _, item_id = shop
    other = Tenant(name="Other", api_key=generate_api_key())
    db.add(other)
    db.commit()
    llm = _FakeLLM(ItemEnrichment())

    result = enrich_item(db, other.id, item_id, llm=llm, embeddings=_FakeEmbeddings())

    assert result.status == "failed"
