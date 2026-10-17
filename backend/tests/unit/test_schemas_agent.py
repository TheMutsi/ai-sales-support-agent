import pytest
from pydantic import ValidationError

from app.schemas.agent import Intent, IntentClassification


def _classification(**scores):
    return IntentClassification(intent=Intent.SMALL_TALK, reasoning="x", **scores)


def test_a_score_on_a_0_to_100_scale_is_read_as_a_percentage():
    """qwen2.5 sometimes answers `100` for 'certain'; rejecting it failed the whole turn."""
    result = _classification(confidence=100, safety_confidence=85)

    assert result.confidence == 1.0
    assert result.safety_confidence == 0.85


def test_scores_already_between_zero_and_one_are_unchanged():
    result = _classification(confidence=0.4, safety_confidence=1)

    assert (result.confidence, result.safety_confidence) == (0.4, 1.0)


@pytest.mark.parametrize("score", [-0.1, 100.5, 1000])
def test_scores_that_fit_neither_scale_are_still_rejected(score):
    with pytest.raises(ValidationError):
        _classification(confidence=score, safety_confidence=1.0)
