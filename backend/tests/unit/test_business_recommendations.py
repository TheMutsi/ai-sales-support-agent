import pytest

from app.business.recommendations import (
    MAX_RECOMMENDATIONS,
    Candidate,
    RankedItem,
    cross_sell,
    rank_by_tags,
    upsell,
)


def _item(item_id, tags=None, **overrides) -> Candidate:
    base = {"item_id": item_id, "tag_weights": tags or {}}
    return Candidate(**{**base, **overrides})


def test_scores_are_the_sum_of_matched_tag_weights():
    items = [_item("a", {"dry": 3, "calm": 2, "vegan": 9}), _item("b", {"dry": 4})]
    ranked = rank_by_tags(items, frozenset({"dry", "calm"}))
    assert ranked == [RankedItem("a", 5), RankedItem("b", 4)]


def test_empty_input_ranks_nothing():
    assert rank_by_tags([], frozenset({"dry"})) == []
    assert rank_by_tags([_item("a", {"dry": 1})], frozenset()) == []


def test_items_without_a_match_are_dropped():
    assert rank_by_tags([_item("a", {"oily": 5})], frozenset({"dry"})) == []


def test_relative_cut_drops_items_far_below_the_best():
    items = [_item("a", {"t": 10}), _item("b", {"t": 6}), _item("c", {"t": 4})]
    assert [r.item_id for r in rank_by_tags(items, frozenset({"t"}))] == ["a", "b"]


def test_item_exactly_at_the_cut_is_kept():
    items = [_item("a", {"t": 10}), _item("b", {"t": 5})]
    assert [r.item_id for r in rank_by_tags(items, frozenset({"t"}))] == ["a", "b"]


def test_ties_are_ordered_by_item_id():
    items = [_item("b", {"t": 2}), _item("a", {"t": 2})]
    assert [r.item_id for r in rank_by_tags(items, frozenset({"t"}))] == ["a", "b"]


def test_never_returns_more_than_the_maximum():
    items = [_item(f"i{n}", {"t": 5}) for n in range(9)]
    assert len(rank_by_tags(items, frozenset({"t"}))) == MAX_RECOMMENDATIONS


def test_limit_above_the_maximum_is_clamped_and_one_returns_one():
    items = [_item(f"i{n}", {"t": 5}) for n in range(9)]
    assert len(rank_by_tags(items, frozenset({"t"}), limit=1)) == 1
    assert len(rank_by_tags(items, frozenset({"t"}), limit=99)) == MAX_RECOMMENDATIONS


def test_zero_or_negative_limit_returns_nothing():
    items = [_item("a", {"t": 1.0})]
    assert rank_by_tags(items, frozenset({"t"}), limit=0) == []
    assert rank_by_tags(items, frozenset({"t"}), limit=-3) == []


def test_scores_are_float_sums_of_fractional_weights():
    items = [_item("a", {"dry": 0.5, "calm": 0.25}), _item("b", {"dry": 0.5})]
    ranked = rank_by_tags(items, frozenset({"dry", "calm"}))
    assert ranked == [RankedItem("a", 0.75), RankedItem("b", 0.5)]


def test_relative_cut_applies_to_fractional_scores():
    items = [_item("a", {"t": 0.9}), _item("b", {"t": 0.4})]
    assert [r.item_id for r in rank_by_tags(items, frozenset({"t"}))] == ["a"]


def test_duplicate_item_ids_are_rejected_when_ranking():
    items = [_item("a", {"t": 1.0}), _item("a", {"t": 2.0})]
    with pytest.raises(ValueError):
        rank_by_tags(items, frozenset({"t"}))


def test_duplicate_item_ids_are_rejected_in_cross_sell_and_upsell():
    current = _item("a", {"t": 1.0})
    catalog = [current, _item("b"), _item("b")]
    with pytest.raises(ValueError):
        cross_sell([current], catalog, frozenset())
    with pytest.raises(ValueError):
        upsell(current, catalog, frozenset())


def test_cross_sell_matches_the_complement_tags_of_the_chosen_items():
    chosen = [_item("cleanser", complement_tags=frozenset({"moisturizer"}))]
    catalog = [
        chosen[0],
        _item("cream", {"moisturizer": 4}),
        _item("soap", {"cleanser": 4}),
    ]
    assert [r.item_id for r in cross_sell(chosen, catalog, frozenset())] == ["cream"]


def test_cross_sell_excludes_chosen_and_already_bought_items():
    chosen = [_item("a", {"x": 5}, complement_tags=frozenset({"x"}))]
    catalog = [chosen[0], _item("b", {"x": 5}), _item("c", {"x": 5})]
    ranked = cross_sell(chosen, catalog, frozenset({"b"}))
    assert [r.item_id for r in ranked] == ["c"]


def test_cross_sell_with_nothing_chosen_recommends_nothing():
    assert cross_sell([], [_item("a", {"x": 1})], frozenset()) == []


def test_co_purchase_counts_override_tag_matching():
    chosen = [_item("a", complement_tags=frozenset({"x"}))]
    catalog = [chosen[0], _item("tagged", {"x": 9}), _item("popular"), _item("rare")]
    ranked = cross_sell(
        chosen, catalog, frozenset(), co_purchases={"a": {"popular": 7, "rare": 1}}
    )
    assert [r.item_id for r in ranked] == ["popular"]


def test_co_purchase_still_excludes_bought_and_chosen_items():
    chosen = [_item("a")]
    catalog = [chosen[0], _item("b"), _item("c")]
    ranked = cross_sell(
        chosen, catalog, frozenset({"b"}), co_purchases={"a": {"a": 9, "b": 8, "c": 2}}
    )
    assert [r.item_id for r in ranked] == ["c"]


def test_empty_co_purchases_fall_back_to_tags():
    chosen = [_item("a", complement_tags=frozenset({"x"}))]
    catalog = [chosen[0], _item("b", {"x": 2})]
    ranked = cross_sell(chosen, catalog, frozenset(), co_purchases={})
    assert [r.item_id for r in ranked] == ["b"]


def test_co_purchase_pointing_at_unknown_or_bought_items_falls_back_to_tags():
    chosen = [_item("a", complement_tags=frozenset({"x"}))]
    catalog = [chosen[0], _item("b", {"x": 0.5}), _item("bought")]
    ranked = cross_sell(
        chosen,
        catalog,
        frozenset({"bought"}),
        co_purchases={"a": {"ghost": 9, "bought": 4, "a": 3}},
    )
    assert [r.item_id for r in ranked] == ["b"]


def test_zero_co_purchase_counts_do_not_block_the_tag_path():
    chosen = [_item("a", complement_tags=frozenset({"x"}))]
    catalog = [chosen[0], _item("b", {"x": 0.5})]
    ranked = cross_sell(chosen, catalog, frozenset(), co_purchases={"a": {"b": 0}})
    assert [r.item_id for r in ranked] == ["b"]


def test_upsell_prefers_the_next_bigger_pack_of_the_same_product():
    current = _item("s1", product_id="serum", pack_size=1, price_tier=1)
    catalog = [
        current,
        _item("s3", product_id="serum", pack_size=3),
        _item("s2", product_id="serum", pack_size=2),
        _item("other", product_id="mask", pack_size=5),
    ]
    assert upsell(current, catalog, frozenset()) == "s2"


def test_upsell_falls_back_to_the_same_need_one_tier_up():
    current = _item("a", {"hydrate": 3}, price_tier=1)
    catalog = [
        current,
        _item("two_up", {"hydrate": 5}, price_tier=3),
        _item("wrong_need", {"calm": 5}, price_tier=2),
        _item("next", {"hydrate": 2}, price_tier=2),
    ]
    assert upsell(current, catalog, frozenset()) == "next"


def test_upsell_picks_the_best_matching_item_within_the_tier():
    current = _item("a", {"hydrate": 3, "calm": 1}, price_tier=1)
    catalog = [
        current,
        _item("weak", {"hydrate": 1}, price_tier=2),
        _item("strong", {"hydrate": 3, "calm": 2}, price_tier=2),
    ]
    assert upsell(current, catalog, frozenset()) == "strong"


def test_upsell_skips_items_already_bought():
    current = _item("a", {"hydrate": 3}, price_tier=1)
    catalog = [current, _item("next", {"hydrate": 2}, price_tier=2)]
    assert upsell(current, catalog, frozenset({"next"})) is None


def test_upsell_is_none_when_there_is_nothing_bigger():
    current = _item("a", {"hydrate": 3}, product_id="p", pack_size=3, price_tier=3)
    assert upsell(current, [current], frozenset()) is None


def test_upsell_ignores_packs_when_sizes_are_unknown():
    current = _item("a", product_id="p", pack_size=None, price_tier=1)
    catalog = [current, _item("b", product_id="p", pack_size=3, price_tier=1)]
    assert upsell(current, catalog, frozenset()) is None
