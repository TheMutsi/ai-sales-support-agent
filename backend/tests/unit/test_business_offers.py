import pytest

from app.business.offers import Offer, OfferDisplay, OfferKind, best_offer_display


def test_no_offers_shows_the_plain_price():
    assert best_offer_display(2_000, []) == OfferDisplay(2_000, None, 0)


def test_discount_offer_strikes_through_the_base_price():
    offer = Offer(OfferKind.DISCOUNT, percent=25)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(1_500, 2_000, 25)


def test_discount_offer_rounds_half_up_in_cents():
    offer = Offer(OfferKind.DISCOUNT, percent=15)
    assert best_offer_display(1_999, [offer]).price_cents == 1_699


def test_pack_offer_compares_against_buying_singles():
    offer = Offer(OfferKind.PACK, quantity=3, price_cents=4_500)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(4_500, 6_000, 25)


def test_bundle_offer_compares_against_the_list_price_of_its_parts():
    offer = Offer(OfferKind.BUNDLE, price_cents=5_000, compare_at_cents=6_250)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(5_000, 6_250, 20)


def test_best_offer_is_the_one_with_the_biggest_discount():
    percent = Offer(OfferKind.DISCOUNT, percent=10)
    pack = Offer(OfferKind.PACK, quantity=2, price_cents=3_000)
    assert best_offer_display(2_000, [percent, pack]).discount_percent == 25


def test_equal_discounts_keep_the_first_offer():
    first = Offer(OfferKind.DISCOUNT, percent=20)
    second = Offer(OfferKind.PACK, quantity=5, price_cents=8_000)
    assert best_offer_display(2_000, [first, second]).price_cents == 1_600


def test_an_offer_that_does_not_lower_the_price_is_ignored():
    offer = Offer(OfferKind.PACK, quantity=2, price_cents=4_500)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(2_000, None, 0)


def test_inactive_offers_are_ignored():
    offer = Offer(OfferKind.DISCOUNT, percent=50, active=False)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(2_000, None, 0)


def test_discount_offer_from_a_stored_price_and_compare_at_price():
    offer = Offer(OfferKind.DISCOUNT, price_cents=1_500, compare_at_cents=2_000)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(1_500, 2_000, 25)


def test_discount_outside_zero_to_one_hundred_is_rejected():
    for percent in (-1, 101):
        with pytest.raises(ValueError):
            best_offer_display(2_000, [Offer(OfferKind.DISCOUNT, percent=percent)])


def test_compare_at_defaults_to_no_struck_price():
    assert Offer(OfferKind.DISCOUNT).compare_at_cents is None


def test_offer_kind_values_match_the_stored_kinds():
    assert [kind.value for kind in OfferKind] == ["pack", "discount", "bundle"]


def test_discount_priced_from_compare_at_wins_over_a_percent():
    offer = Offer(OfferKind.DISCOUNT, percent=90, price_cents=1_500, compare_at_cents=2_000)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(1_500, 2_000, 25)


def test_discount_with_compare_at_not_above_price_and_no_percent_is_ignored():
    for compare_at in (None, 1_500, 1_000):
        offer = Offer(OfferKind.DISCOUNT, price_cents=1_500, compare_at_cents=compare_at)
        assert best_offer_display(2_000, [offer]) == OfferDisplay(2_000, None, 0)


def test_bundle_without_a_compare_at_price_is_ignored():
    offer = Offer(OfferKind.BUNDLE, price_cents=1_000)
    assert best_offer_display(2_000, [offer]) == OfferDisplay(2_000, None, 0)


def test_negative_price_is_rejected():
    offer = Offer(OfferKind.BUNDLE, price_cents=-1, compare_at_cents=100)
    with pytest.raises(ValueError):
        best_offer_display(2_000, [offer])


def test_pack_with_a_non_positive_price_or_quantity_is_rejected():
    for offer in (
        Offer(OfferKind.PACK, quantity=2, price_cents=0),
        Offer(OfferKind.PACK, quantity=0, price_cents=500),
        Offer(OfferKind.PACK, quantity=-1, price_cents=500),
    ):
        with pytest.raises(ValueError):
            best_offer_display(2_000, [offer])


def test_negative_base_price_is_rejected_with_or_without_offers():
    with pytest.raises(ValueError):
        best_offer_display(-5, [])
    with pytest.raises(ValueError):
        best_offer_display(-5, [Offer(OfferKind.DISCOUNT, percent=10)])


def test_inactive_invalid_offers_are_not_validated():
    offer = Offer(OfferKind.DISCOUNT, percent=500, active=False)
    assert best_offer_display(2_000, [offer]).discount_percent == 0
