"""Unit tests for the guardrail node: no LLM involved, it only inspects the
message `response_writer` already produced against the rest of the state."""

from langchain_core.messages import AIMessage

from app.agent.nodes.guardrail import guardrail_node


def test_returns_empty_update_for_a_clean_response():
    state = {
        "intent": None,
        "checkout_session": None,
        "messages": [AIMessage(content="Claro, te cuento las funciones del plan Pro.")],
    }
    assert guardrail_node(state) == {}


def test_replaces_the_message_in_place_on_a_blocked_violation():
    original = AIMessage(content="Tu reembolso será aprobado en breve.", id="msg-1")
    state = {"intent": None, "checkout_session": None, "messages": [original]}

    result = guardrail_node(state)

    assert result["guardrail_flags"] == ["unconfirmed_refund_claim"]
    replacement = result["messages"][0]
    assert replacement.id == "msg-1"
    assert replacement.content != original.content


def test_flag_only_violation_keeps_the_original_message():
    from app.schemas.agent import Intent

    original = AIMessage(content="Podría haber habido un sobrecosto en tu facturación.", id="msg-2")
    state = {"intent": Intent.BILLING_QUESTION, "checkout_session": None, "messages": [original]}

    result = guardrail_node(state)

    assert result["guardrail_flags"] == ["unverified_billing_explanation"]
    assert "messages" not in result
