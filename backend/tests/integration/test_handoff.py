"""A person takes over from the assistant: an escalation puts the conversation in a waiting state,
and from then on the visitor's messages are stored and the assistant does not answer them."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app.api import chat as chat_module
from app.auth.conversations import resolve_for_login
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.chat.turns import (
    ESCALATION_NOTICE,
    HandoffStatus,
    MessageIdReused,
    TurnAction,
    begin_turn,
    finish_turn,
    list_messages,
)
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Message, Tenant, Ticket
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def shop(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        customer = Customer(name="Ana", email="ana@shop.test", tenant_id=tenant.id)
        db.add(customer)
        db.flush()
        conversation = resolve_for_login(
            db, tenant_id=tenant.id, customer_id=customer.id, level=IdentityLevel.STORE_LOGIN,
            conversation_id=None, now=NOW,
        )
        ticket = Ticket(customer_id=customer.id, category="escalation", subject="s", description="d")
        db.add(ticket)
        db.commit()
        yield {"db": db, "tenant": tenant, "customer": customer, "conversation": conversation, "ticket": ticket}


def _escalate(shop, text="I want a person"):
    """A turn whose reply opened a ticket, as the agent's escalation does."""
    db, conversation = shop["db"], shop["conversation"]
    turn = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content=text, now=NOW)
    finish_turn(
        db, conversation_id=conversation.id, turn=turn, content="A ticket was opened.", now=NOW,
        escalation_ticket_id=shop["ticket"].id,
    )


def _state(shop) -> Conversation:
    shop["db"].expire_all()
    return shop["db"].get(Conversation, shop["conversation"].id)


def test_an_escalation_puts_the_conversation_in_the_waiting_state_with_a_notice(shop):
    _escalate(shop)

    conversation = _state(shop)
    assert conversation.handoff_status == HandoffStatus.WAITING
    assert conversation.handoff_ticket_id == shop["ticket"].id
    assert conversation.handoff_requested_at is not None
    stored = list_messages(shop["db"], conversation_id=conversation.id)
    assert [(m.role, m.kind) for m in stored] == [("user", "text"), ("assistant", "text"), ("system", "system")]
    assert stored[1].reply_to_seq == 1  # the reply still answers the message
    assert stored[2].content == ESCALATION_NOTICE


def test_a_turn_without_a_ticket_does_not_wait_for_a_person(shop):
    db, conversation = shop["db"], shop["conversation"]
    turn = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content="hi", now=NOW)
    finish_turn(db, conversation_id=conversation.id, turn=turn, content="hello", now=NOW)
    assert _state(shop).handoff_status == HandoffStatus.NONE


def test_while_a_person_has_the_conversation_a_message_is_stored_and_not_answered(shop):
    _escalate(shop)
    db, conversation = shop["db"], shop["conversation"]

    turn = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content="hello?", now=NOW)

    assert (turn.action, turn.handoff) == (TurnAction.HANDOFF, HandoffStatus.WAITING)
    fresh = _state(shop)
    assert fresh.turn_id is None and fresh.turn_started_at is None  # no agent turn is running
    assert list_messages(db, conversation_id=conversation.id)[-1].content == "hello?"


def test_a_retry_while_a_person_has_the_conversation_is_not_stored_twice(shop):
    _escalate(shop)
    db, conversation, message_id = shop["db"], shop["conversation"], uuid.uuid4()
    for _ in range(2):
        turn = begin_turn(db, conversation_id=conversation.id, client_message_id=message_id, content="hello?", now=NOW)
        assert turn.action is TurnAction.HANDOFF
    texts = [m.content for m in list_messages(db, conversation_id=conversation.id) if m.content == "hello?"]
    assert texts == ["hello?"]
    with pytest.raises(MessageIdReused):
        begin_turn(db, conversation_id=conversation.id, client_message_id=message_id, content="other", now=NOW)


def test_what_a_person_said_is_not_in_the_history_the_assistant_continues_from(shop):
    db, conversation = shop["db"], shop["conversation"]
    first = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content="one", now=NOW)
    finish_turn(db, conversation_id=conversation.id, turn=first, content="reply one", now=NOW)
    db.add_all(
        [
            Message(conversation_id=conversation.id, seq=3, role="human", author_name="Mónica", kind="text",
                    content="a person said this", created_at=NOW),
            Message(conversation_id=conversation.id, seq=4, role="system", kind="system",
                    content="a notice", created_at=NOW),
        ]
    )
    db.query(Conversation).filter_by(id=conversation.id).update({"last_seq": 4})
    db.commit()

    second = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content="two", now=NOW)

    assert [m.content for m in second.history] == ["one", "reply one"]


# --- over HTTP ---------------------------------------------------------------------------------


def _auth(shop) -> dict:
    token, _ = issue_session_token(
        tenant_id=shop["tenant"].id, conversation_id=shop["conversation"].id,
        customer_id=shop["customer"].id, level=IdentityLevel.STORE_LOGIN,
        signing_key=get_settings().session_signing_key, ttl=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


class _Graph:
    def __init__(self):
        self.ran = False

    async def astream_events(self, initial_state, config, version):
        self.ran = True
        final = {"messages": [HumanMessage(content="x"), AIMessage(content="y")]}
        yield {"event": "on_chain_end", "name": "LangGraph", "metadata": {}, "data": {"output": final}}


def test_the_chat_stores_the_message_and_does_not_run_the_assistant_during_a_handoff(shop, monkeypatch):
    _escalate(shop)
    graph = _Graph()
    monkeypatch.setattr(chat_module, "agent_graph", graph)

    response = client.post("/api/chat", json={"message": "are you there?", "message_id": str(uuid.uuid4())}, headers=_auth(shop))

    assert response.status_code == 200
    assert '"handoff": "waiting"' in response.text
    assert "event: message" not in response.text and "event: delta" not in response.text
    assert graph.ran is False
    stored = client.get(f"/api/conversations/{shop['conversation'].id}/messages", headers=_auth(shop)).json()
    assert stored["handoff"] == "waiting"
    assert stored["messages"][-1]["content"] == "are you there?"
    assert stored["messages"][-2]["kind"] == "system"


def test_the_messages_endpoint_says_there_is_no_handoff_in_a_normal_conversation(shop):
    stored = client.get(f"/api/conversations/{shop['conversation'].id}/messages", headers=_auth(shop)).json()
    assert stored["handoff"] == "none"


def test_a_chat_turn_that_opens_a_ticket_leaves_the_conversation_waiting_for_a_person(shop, monkeypatch):
    from types import SimpleNamespace

    final = {
        "messages": [HumanMessage(content="I want a person"), AIMessage(content="A ticket was opened.")],
        "escalated": True,
        "ticket_receipt": SimpleNamespace(ticket_id=shop["ticket"].id),
    }

    class Escalating(_Graph):
        async def astream_events(self, initial_state, config, version):
            yield {"event": "on_chain_end", "name": "LangGraph", "metadata": {}, "data": {"output": final}}

    monkeypatch.setattr(chat_module, "agent_graph", Escalating())

    client.post("/api/chat", json={"message": "I want a person", "message_id": str(uuid.uuid4())}, headers=_auth(shop))

    assert _state(shop).handoff_status == HandoffStatus.WAITING
    assert _state(shop).handoff_ticket_id == shop["ticket"].id
