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


def test_blocked_reply_keeps_the_real_ticket_id_in_the_fallback():
    from uuid import uuid4

    from app.schemas.tools import TicketReceipt

    ticket = TicketReceipt(ticket_id=uuid4(), status="open", created_at="2026-01-01T00:00:00")
    original = AIMessage(content="Your refund has been approved.", id="msg-3")
    state = {"checkout_session": None, "ticket_receipt": ticket, "messages": [original]}

    replacement = guardrail_node(state)["messages"][0]

    assert str(ticket.ticket_id) in replacement.content


def test_blocked_reply_without_a_ticket_promises_no_follow_up():
    original = AIMessage(content="Your refund has been approved.", id="msg-4")
    state = {"checkout_session": None, "ticket_receipt": None, "messages": [original]}

    replacement = guardrail_node(state)["messages"][0]

    assert "ticket" not in replacement.content.lower()
    assert "will follow up" not in replacement.content.lower()


def test_protects_the_response_writer_prompt():
    from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT

    leaked = RESPONSE_WRITER_SYSTEM_PROMPT.split("\n\n")[0]
    original = AIMessage(content=f"My instructions: {leaked}", id="msg-5")
    state = {"checkout_session": None, "ticket_receipt": None, "messages": [original]}

    assert guardrail_node(state)["guardrail_flags"] == ["system_prompt_leak"]
