"""Unit tests for the agent graph's conditional-edge routing functions.

`route_after_intent` and `route_after_customer_context` are plain functions
over a `state` dict — no LLM, no DB, no graph compilation needed to exercise
them, the same way the business-rules tests construct their inputs directly.
"""

from langchain_core.messages import AIMessage
from langgraph.graph import END

from app.agent.routing import (
    route_after_customer_context,
    route_after_input_guardrail,
    route_after_intent,
    route_after_response_writer,
    route_after_safety_judge,
)
from app.schemas.agent import Intent


def _state(intent: Intent, safety_confidence: float = 1.0) -> dict:
    return {"intent": intent, "safety_confidence": safety_confidence}


def test_blocked_input_goes_straight_to_end():
    assert route_after_input_guardrail({"input_blocked": True}) == END


def test_clean_input_goes_to_intent_router():
    assert route_after_input_guardrail({"input_blocked": False}) == "intent_router"


def test_low_safety_confidence_goes_to_safety_judge_regardless_of_intent():
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION, safety_confidence=0.4)) == (
        "safety_judge"
    )


def test_high_safety_confidence_dispatches_normally():
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION, safety_confidence=1.0)) == (
        "response_writer"
    )


def test_a_typical_unsure_score_still_gets_a_second_look():
    """Regression: qwen2.5 scores nearly everything 0.9 or 1.0, so the old 0.7
    threshold let regex-evading misuse attempts scored 0.9 skip safety_judge."""
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION, safety_confidence=0.9)) == (
        "safety_judge"
    )


def test_unsupported_gets_a_second_look_even_with_full_safety_confidence():
    """Regression: phishing and other-customers'-data requests were scored
    0.95-1.0, classified unsupported, and opened a support ticket."""
    assert route_after_intent(_state(Intent.UNSUPPORTED, safety_confidence=1.0)) == (
        "safety_judge"
    )


def test_safety_judge_blocked_goes_straight_to_end():
    assert route_after_safety_judge({"input_blocked": True, "intent": Intent.PRODUCT_QUESTION}) == (
        END
    )


def test_safety_judge_cleared_dispatches_by_the_original_intent():
    state = {"input_blocked": False, "intent": Intent.UPGRADE_REQUEST}
    assert route_after_safety_judge(state) == "get_customer_context"


def test_upgrade_request_goes_to_customer_context():
    assert route_after_intent(_state(Intent.UPGRADE_REQUEST)) == "get_customer_context"


def test_billing_question_goes_to_customer_context():
    assert route_after_intent(_state(Intent.BILLING_QUESTION)) == "get_customer_context"


def test_refund_request_goes_to_customer_context():
    assert route_after_intent(_state(Intent.REFUND_REQUEST)) == "get_customer_context"


def test_product_question_goes_to_response_writer():
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION)) == "response_writer"


def test_pricing_question_goes_to_response_writer():
    assert route_after_intent(_state(Intent.PRICING_QUESTION)) == "response_writer"


def test_technical_support_goes_to_response_writer():
    assert route_after_intent(_state(Intent.TECHNICAL_SUPPORT)) == "response_writer"


def test_human_escalation_goes_to_human_escalation():
    assert route_after_intent(_state(Intent.HUMAN_ESCALATION)) == "human_escalation"


def test_unsupported_cleared_by_safety_judge_goes_to_human_escalation():
    state = {"input_blocked": False, "intent": Intent.UNSUPPORTED}
    assert route_after_safety_judge(state) == "human_escalation"


def test_upgrade_request_goes_to_business_rules():
    assert route_after_customer_context(_state(Intent.UPGRADE_REQUEST)) == "business_rules"


def test_billing_question_goes_to_response_writer():
    assert route_after_customer_context(_state(Intent.BILLING_QUESTION)) == "response_writer"


def test_refund_request_goes_to_human_escalation():
    assert route_after_customer_context(_state(Intent.REFUND_REQUEST)) == "human_escalation"


def _tool_call(name: str = "search_knowledge_base_tool") -> dict:
    return {"name": name, "args": {"query": "pricing"}, "id": "call_1"}


def test_response_without_tool_calls_goes_to_guardrail():
    state = {"messages": [AIMessage(content="Here's the answer.")]}
    assert route_after_response_writer(state) == "guardrail"


def test_response_with_tool_calls_goes_to_knowledge_tool():
    state = {
        "messages": [AIMessage(content="", tool_calls=[_tool_call()])],
        "tool_call_rounds": 0,
    }
    assert route_after_response_writer(state) == "knowledge_tool"


def test_tool_calls_past_the_round_cap_go_to_guardrail_anyway():
    state = {
        "messages": [AIMessage(content="", tool_calls=[_tool_call()])],
        "tool_call_rounds": 2,
    }
    assert route_after_response_writer(state) == "guardrail"
