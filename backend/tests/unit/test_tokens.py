import pytest

from app.rag.tokens import estimate_tokens


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("a", 1), ("abc", 1), ("abcd", 2), ("a" * 300, 100), ("a" * 301, 101)],
)
def test_estimate_tokens_is_the_length_over_three_rounded_up(text: str, expected: int):
    assert estimate_tokens(text) == expected
