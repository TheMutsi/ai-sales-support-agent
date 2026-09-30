"""Unit tests for the agent graph's conditional-edge routing functions.

`route_after_intent` and `route_after_customer_context` are plain functions
over a `state` dict — no LLM, no DB, no graph compilation needed to exercise
them, the same way the business-rules tests construct their inputs directly.
"""

from langgraph.graph import END

from app.agent.routing import route_after_customer_context, route_after_intent
from app.schemas.agent import Intent


def _state(intent: Intent) -> dict:
    return {"intent": intent}


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


def test_human_escalation_and_unsupported_end_the_graph_for_now():
    # No human_escalation node yet — lands in a follow-up PR.
    assert route_after_intent(_state(Intent.HUMAN_ESCALATION)) == END
    assert route_after_intent(_state(Intent.UNSUPPORTED)) == END


def test_upgrade_request_goes_to_business_rules():
    assert route_after_customer_context(_state(Intent.UPGRADE_REQUEST)) == "business_rules"


def test_billing_and_refund_end_the_graph_for_now():
    # No response_writer/human_escalation node yet — lands in a follow-up PR.
    assert route_after_customer_context(_state(Intent.BILLING_QUESTION)) == END
    assert route_after_customer_context(_state(Intent.REFUND_REQUEST)) == END
