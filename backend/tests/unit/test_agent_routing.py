"""Unit tests for the agent graph's conditional-edge routing functions.

`route_after_intent` and `route_after_customer_context` are plain functions
over a `state` dict — no LLM, no DB, no graph compilation needed to exercise
them, the same way the business-rules tests construct their inputs directly.
"""

from langgraph.graph import END

from app.agent.routing import (
    route_after_customer_context,
    route_after_input_guardrail,
    route_after_intent,
)
from app.schemas.agent import Intent


def _state(intent: Intent) -> dict:
    return {"intent": intent}


def test_blocked_input_goes_straight_to_end():
    assert route_after_input_guardrail({"input_blocked": True}) == END


def test_clean_input_goes_to_intent_router():
    assert route_after_input_guardrail({"input_blocked": False}) == "intent_router"


def test_upgrade_request_goes_to_customer_context():
    assert route_after_intent(_state(Intent.UPGRADE_REQUEST)) == "get_customer_context"


def test_billing_question_goes_to_customer_context():
    assert route_after_intent(_state(Intent.BILLING_QUESTION)) == "get_customer_context"


def test_refund_request_goes_to_customer_context():
    assert route_after_intent(_state(Intent.REFUND_REQUEST)) == "get_customer_context"


def test_product_question_goes_to_retrieve_knowledge():
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION)) == "retrieve_knowledge"


def test_pricing_question_goes_to_retrieve_knowledge():
    assert route_after_intent(_state(Intent.PRICING_QUESTION)) == "retrieve_knowledge"


def test_technical_support_goes_to_retrieve_knowledge():
    assert route_after_intent(_state(Intent.TECHNICAL_SUPPORT)) == "retrieve_knowledge"


def test_human_escalation_goes_to_human_escalation():
    assert route_after_intent(_state(Intent.HUMAN_ESCALATION)) == "human_escalation"


def test_unsupported_goes_to_human_escalation():
    assert route_after_intent(_state(Intent.UNSUPPORTED)) == "human_escalation"


def test_upgrade_request_goes_to_business_rules():
    assert route_after_customer_context(_state(Intent.UPGRADE_REQUEST)) == "business_rules"


def test_billing_question_goes_to_response_writer():
    assert route_after_customer_context(_state(Intent.BILLING_QUESTION)) == "response_writer"


def test_refund_request_goes_to_human_escalation():
    assert route_after_customer_context(_state(Intent.REFUND_REQUEST)) == "human_escalation"
