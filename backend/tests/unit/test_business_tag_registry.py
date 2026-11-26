import pytest

from app.business.tag_registry import (
    NEAR_DUPLICATE_SIMILARITY,
    cosine_similarity,
    find_near_duplicate,
    normalize_slug,
)


def test_slug_is_lowercase_words_joined_by_dashes():
    assert normalize_slug("  Dry Skin!! ") == "dry-skin"


def test_slug_drops_accents():
    assert normalize_slug("Hidratación profunda") == "hidratacion-profunda"


def test_slug_collapses_symbols_and_trims_dashes():
    assert normalize_slug("--anti_aging / firming--") == "anti-aging-firming"


def test_slug_is_cut_to_a_maximum_length_without_a_trailing_dash():
    slug = normalize_slug("a" * 39 + " " + "b" * 10)
    assert len(slug) <= 40
    assert not slug.endswith("-")


def test_a_slug_with_no_usable_characters_is_rejected():
    with pytest.raises(ValueError):
        normalize_slug("!!! ???")


def test_cosine_similarity_of_identical_and_orthogonal_vectors():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_similarity_with_a_zero_vector_is_zero():
    assert cosine_similarity([0, 0], [1, 1]) == 0.0


def test_cosine_similarity_rejects_vectors_of_different_size():
    with pytest.raises(ValueError):
        cosine_similarity([1, 0], [1, 0, 0])


def test_near_duplicate_returns_the_closest_slug_above_the_threshold():
    registry = {"firming": [1.0, 0.0], "calming": [0.0, 1.0]}
    assert find_near_duplicate([0.99, 0.05], registry) == "firming"


def test_nothing_is_returned_when_no_tag_is_close_enough():
    registry = {"firming": [1.0, 0.0]}
    assert find_near_duplicate([0.6, 0.8], registry) is None


def test_a_tag_exactly_at_the_threshold_counts_as_a_duplicate():
    registry = {"firming": [1.0, 0.0]}
    vector = [NEAR_DUPLICATE_SIMILARITY, (1 - NEAR_DUPLICATE_SIMILARITY**2) ** 0.5]
    assert find_near_duplicate(vector, registry) == "firming"


def test_an_empty_registry_has_no_duplicate():
    assert find_near_duplicate([1.0, 0.0], {}) is None


def test_ties_go_to_the_alphabetically_first_slug():
    registry = {"b-tag": [1.0, 0.0], "a-tag": [1.0, 0.0]}
    assert find_near_duplicate([1.0, 0.0], registry) == "a-tag"
