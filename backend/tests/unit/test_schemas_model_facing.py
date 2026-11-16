from langchain_core.utils.function_calling import convert_to_openai_tool

from app.schemas.agent import IntentClassification, ReturnReading
from app.schemas.guardrails import SafetyJudgment


def _function(model) -> dict:
    return convert_to_openai_tool(model)["function"]


def test_the_intent_enum_is_described_to_the_classifier():
    intent = _function(IntentClassification)["parameters"]["properties"]["intent"]
    assert "intent_router" in intent["description"]


def test_return_reading_tells_the_model_rules_decide_the_rest():
    function = _function(ReturnReading)
    assert "decided by rules" in function["description"]
    assert function["parameters"]["properties"]["choice"]["description"]


def test_safety_judgment_is_described_to_the_judge():
    assert "second opinion" in _function(SafetyJudgment)["description"]
