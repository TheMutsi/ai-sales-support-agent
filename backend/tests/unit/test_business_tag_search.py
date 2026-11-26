from app.business.recommendations import RankedItem
from app.business.tag_search import (
    MAX_QUERY_TAGS,
    WEAK_SCORE,
    fuse_rankings,
    is_weak,
    validate_selection,
)

REGISTRY = {"dry-skin", "firming", "calming", "vegan", "spf", "night"}


def test_unknown_tags_are_dropped():
    assert validate_selection(["firming", "made-up"], REGISTRY) == ["firming"]


def test_slugs_are_normalized_before_checking():
    assert validate_selection(["Dry Skin", "FIRMING"], REGISTRY) == ["dry-skin", "firming"]


def test_duplicates_are_removed_keeping_the_first_position():
    assert validate_selection(["firming", "calming", "firming"], REGISTRY) == ["firming", "calming"]


def test_at_most_five_tags_are_kept():
    chosen = validate_selection(sorted(REGISTRY), REGISTRY)
    assert len(chosen) == MAX_QUERY_TAGS == 5


def test_an_unusable_slug_is_ignored_not_an_error():
    assert validate_selection(["!!!", "vegan"], REGISTRY) == ["vegan"]


def test_nothing_ranked_is_weak():
    assert is_weak([]) is True


def test_a_best_score_below_the_floor_is_weak():
    assert is_weak([RankedItem("a", WEAK_SCORE - 0.01)]) is True


def test_a_best_score_at_the_floor_is_not_weak():
    assert is_weak([RankedItem("a", WEAK_SCORE)]) is False


def test_fusion_rewards_items_present_in_both_rankings():
    scores = fuse_rankings([["a", "b", "c"], ["c", "a"]])
    assert [item for item, _ in scores] == ["a", "c", "b"]


def test_fusion_breaks_ties_by_id():
    scores = fuse_rankings([["b"], ["a"]])
    assert [item for item, _ in scores] == ["a", "b"]


def test_fusion_of_nothing_is_empty():
    assert fuse_rankings([[], []]) == []
