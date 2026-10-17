from langchain_core.messages import AIMessage

from app.agent.nodes.request_identity import request_identity_node
from app.schemas.agent import Intent


def _run(scopes, overrides=None, intent=Intent.BILLING_QUESTION):
    return request_identity_node(
        {"intent": intent, "scopes": scopes, "scope_overrides": overrides, "messages": []}
    )


def test_it_asks_for_identification_with_a_fixed_text_and_the_methods_to_offer():
    result = _run(["kb:read"])

    assert result["identity_required"] is True
    assert result["identity_methods"] == ["otp"]
    [message] = result["messages"]
    assert isinstance(message, AIMessage) and "verify" in message.content.lower()


def test_the_methods_follow_the_scope_the_question_needs():
    result = _run(["kb:read"], intent=Intent.REFUND_REQUEST)

    assert result["identity_methods"] == ["otp"]


def test_when_the_tenant_leaves_no_method_it_points_to_the_shops_own_login():
    result = _run(["kb:read"], overrides={"otp_login": ["kb:read"]})

    assert result["identity_methods"] == []
    assert "log in" in result["messages"][0].content.lower()


def test_a_customer_step_refuses_to_run_without_a_customer():
    import pytest

    from app.agent.nodes.business_rules import business_rules_node
    from app.agent.nodes.customer_context import get_customer_context_node
    from app.agent.nodes.human_escalation import human_escalation_node

    state = {"customer_id": None, "intent": Intent.UPGRADE_REQUEST, "messages": []}
    for node in (get_customer_context_node, business_rules_node, human_escalation_node):
        with pytest.raises(PermissionError):
            node(state)


def test_a_visitor_who_already_has_a_scope_but_no_order_is_offered_only_the_order_form():
    """A customer verified with a code needs no second code to look an order up: what is
    missing is the order, so only that method is offered."""
    result = request_identity_node(
        {
            "intent": Intent.ORDER_STATUS,
            "scopes": ["kb:read", "order:read", "customer:read"],
            "scope_overrides": None,
            "order_id": None,
            "messages": [],
        }
    )

    assert result["identity_methods"] == ["order_id"]


def test_an_anonymous_visitor_asking_about_an_order_is_offered_both_methods():
    assert _run(["kb:read"], intent=Intent.ORDER_STATUS)["identity_methods"] == ["otp", "order_id"]

