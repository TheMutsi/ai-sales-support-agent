import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.credentials import generate_api_key
from app.db.models import (
    ItemOffer,
    ItemTag,
    RecommendationItem,
    RecommendationTag,
    RecommendationType,
    Tenant,
)
from app.db.seed import DEV_TENANT_API_KEY, seed
from app.db.session import SessionLocal


@pytest.fixture
def two_tenants(tenant_wipe):
    with SessionLocal() as db:
        a = Tenant(name="Shop A", api_key=generate_api_key())
        b = Tenant(name="Shop B", api_key=generate_api_key())
        db.add_all([a, b])
        db.commit()
        yield a.id, b.id


def _type(db, tenant_id, key="product"):
    item_type = RecommendationType(tenant_id=tenant_id, key=key, name=key.title(), card_template="product_card")
    db.add(item_type)
    db.flush()
    return item_type


def _item(db, tenant_id, type_id, external_id="sku-1"):
    item = RecommendationItem(
        tenant_id=tenant_id, type_id=type_id, external_id=external_id, title="Cream", price_cents=1000
    )
    db.add(item)
    db.flush()
    return item


def _tag(db, tenant_id, slug="cleanser"):
    tag = RecommendationTag(tenant_id=tenant_id, slug=slug)
    db.add(tag)
    db.flush()
    return tag


def _catalog_counts(db):
    return tuple(
        db.query(model).count()
        for model in (RecommendationType, RecommendationItem, ItemOffer, RecommendationTag, ItemTag)
    )


def test_two_tenants_can_use_the_same_external_id_and_tag_slug(two_tenants):
    a, b = two_tenants
    with SessionLocal() as db:
        for tenant_id in (a, b):
            _item(db, tenant_id, _type(db, tenant_id).id)
            _tag(db, tenant_id)
        db.commit()

        assert db.query(RecommendationItem).filter_by(external_id="sku-1").count() == 2
        assert db.query(RecommendationTag).filter_by(slug="cleanser").count() == 2


def test_one_tenant_cannot_repeat_an_external_id(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        type_id = _type(db, a).id
        _item(db, a, type_id)
        db.commit()

        db.add(
            RecommendationItem(tenant_id=a, type_id=type_id, external_id="sku-1", title="Other", price_cents=1)
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_an_item_cannot_use_another_tenants_type(two_tenants):
    a, b = two_tenants
    with SessionLocal() as db:
        foreign_type_id = _type(db, b).id
        db.commit()

        db.add(
            RecommendationItem(tenant_id=a, type_id=foreign_type_id, external_id="x", title="X", price_cents=1)
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_an_item_cannot_carry_another_tenants_tag(two_tenants):
    a, b = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        foreign_tag = _tag(db, b)
        db.commit()

        db.add(ItemTag(item_id=item.id, tag_id=foreign_tag.id, tenant_id=a, weight=0.5))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("weight", [-0.1, 1.1])
def test_a_tag_weight_outside_zero_to_one_is_rejected(two_tenants, weight):
    a, _ = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        tag = _tag(db, a)
        db.add(ItemTag(item_id=item.id, tag_id=tag.id, tenant_id=a, weight=weight))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("weight", [0.0, 1.0])
def test_a_tag_weight_at_the_bounds_is_accepted(two_tenants, weight):
    a, _ = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        tag = _tag(db, a)
        db.add(ItemTag(item_id=item.id, tag_id=tag.id, tenant_id=a, weight=weight))
        db.commit()


def test_an_unknown_offer_kind_is_rejected(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        db.add(ItemOffer(item_id=item.id, tenant_id=a, kind="raffle", label="x", price_cents=1))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "offer_fields",
    [
        {"price_cents": -1},
        {"price_cents": 1, "compare_at_cents": -1},
        {"price_cents": 1, "quantity": 0},
    ],
)
def test_an_offer_with_a_negative_price_or_no_quantity_is_rejected(two_tenants, offer_fields):
    a, _ = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        db.add(ItemOffer(item_id=item.id, tenant_id=a, kind="pack", label="x", **offer_fields))
        with pytest.raises(IntegrityError):
            db.commit()


def test_an_unknown_card_template_is_rejected(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        db.add(RecommendationType(tenant_id=a, key="x", name="X", card_template="carousel"))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("compare_at_cents", [999, 1000])
def test_a_compare_at_price_not_above_the_price_is_rejected(two_tenants, compare_at_cents):
    a, _ = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        db.add(
            ItemOffer(
                item_id=item.id, tenant_id=a, kind="discount", label="x", price_cents=1000,
                compare_at_cents=compare_at_cents,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_an_offer_without_a_compare_at_price_or_above_the_price_is_accepted(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        db.add(ItemOffer(item_id=item.id, tenant_id=a, kind="pack", label="x", price_cents=1000))
        db.add(
            ItemOffer(
                item_id=item.id, tenant_id=a, kind="discount", label="y", price_cents=1000, compare_at_cents=1001
            )
        )
        db.commit()


def test_an_offer_cannot_point_at_another_tenants_item(two_tenants):
    a, b = two_tenants
    with SessionLocal() as db:
        foreign_item = _item(db, b, _type(db, b).id)
        db.commit()

        db.add(ItemOffer(item_id=foreign_item.id, tenant_id=a, kind="pack", label="x", price_cents=1))
        with pytest.raises(IntegrityError):
            db.commit()


def test_an_item_with_a_negative_price_is_rejected(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        type_id = _type(db, a).id
        db.add(RecommendationItem(tenant_id=a, type_id=type_id, external_id="n", title="N", price_cents=-1))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "bad_fields",
    [
        {"rating": -0.1},
        {"rating": 5.1},
        {"image_url": "http://example.test/a.jpg"},
        {"image_url": "ftp://example.test/a.jpg"},
        {"url": "ftp://example.test/a"},
        {"url": "javascript:alert(1)"},
    ],
)
def test_a_rating_picture_or_link_the_card_refuses_is_rejected(two_tenants, bad_fields):
    a, _ = two_tenants
    with SessionLocal() as db:
        type_id = _type(db, a).id
        db.add(
            RecommendationItem(
                tenant_id=a, type_id=type_id, external_id="b", title="B", price_cents=1, **bad_fields
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "good_fields",
    [
        {},
        {"rating": 0},
        {"rating": 5},
        {"image_url": "https://example.test/a.jpg"},
        {"url": "http://example.test/a"},
        {"url": "HTTPS://example.test/a"},
    ],
)
def test_a_rating_picture_or_link_the_card_accepts_is_stored(two_tenants, good_fields):
    a, _ = two_tenants
    with SessionLocal() as db:
        type_id = _type(db, a).id
        db.add(
            RecommendationItem(
                tenant_id=a, type_id=type_id, external_id="g", title="G", price_cents=1, **good_fields
            )
        )
        db.commit()


def test_an_item_with_a_pack_size_of_zero_is_rejected(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        type_id = _type(db, a).id
        db.add(
            RecommendationItem(
                tenant_id=a, type_id=type_id, external_id="z", title="Z", price_cents=1, pack_size=0
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_pack_variants_share_a_product_id_and_complement_flags_round_trip(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        type_id = _type(db, a).id
        for external_id, pack_size in (("p-1", 1), ("p-3", 3)):
            db.add(
                RecommendationItem(
                    tenant_id=a, type_id=type_id, external_id=external_id, title="P", price_cents=1,
                    product_id="p", pack_size=pack_size,
                )
            )
        item = _item(db, a, type_id)
        tag = _tag(db, a)
        db.add(ItemTag(item_id=item.id, tag_id=tag.id, tenant_id=a, weight=0.5, is_complement=True))
        db.commit()

        assert db.query(RecommendationItem).filter_by(tenant_id=a, product_id="p").count() == 2
        assert db.query(ItemTag).one().is_complement is True


def test_an_unknown_item_status_is_rejected(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        type_id = _type(db, a).id
        db.add(
            RecommendationItem(
                tenant_id=a, type_id=type_id, external_id="y", title="Y", price_cents=1, status="lost"
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_deleting_an_item_removes_its_offers_and_tags(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        item = _item(db, a, _type(db, a).id)
        tag = _tag(db, a)
        db.add(ItemOffer(item_id=item.id, tenant_id=a, kind="pack", label="Pack", quantity=2, price_cents=1800))
        db.add(ItemTag(item_id=item.id, tag_id=tag.id, tenant_id=a, weight=0.5))
        db.commit()

        db.delete(item)
        db.commit()

        assert db.query(ItemOffer).count() == 0
        assert db.query(ItemTag).count() == 0


def test_the_seed_never_updates_or_adds_offers_and_tags_of_items_that_already_exist(tenant_wipe):
    with SessionLocal() as db:
        seed(db)
        offer = db.query(ItemOffer).first()
        offer.label = "edited by hand"
        db.query(ItemTag).filter_by(is_complement=True).delete()
        db.commit()
        counts_before = _catalog_counts(db)

        seed(db)

        assert _catalog_counts(db) == counts_before
        assert db.query(ItemOffer).filter_by(label="edited by hand").count() == 1


def test_the_seed_loads_a_demo_catalog_with_offers_into_the_dev_tenant_once(tenant_wipe):
    with SessionLocal() as db:
        seed(db)
        counts_after_first = _catalog_counts(db)
        seed(db)
        tenant = db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one()

        assert _catalog_counts(db) == counts_after_first
        items = db.query(RecommendationItem).filter_by(tenant_id=tenant.id).all()
        assert len(items) == 6
        assert {i.pack_size for i in items if i.product_id == "moisturizer-daily"} == {1, 3}
        assert db.query(ItemTag).filter_by(is_complement=True).count() >= 1
        assert {item.status for item in items} == {"active"}
        assert db.query(ItemOffer).count() == 3
        assert db.query(ItemOffer).filter_by(kind="pack", quantity=3).count() == 0
        assert db.query(ItemTag).filter_by(tenant_id=tenant.id).count() >= 1
