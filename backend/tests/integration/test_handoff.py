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
from app.db.models import Conversation, Customer, Message, Tenant
from app.db.session import SessionLocal
from app.main import app
from app.schemas.tools import EscalationReceipt

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
        db.commit()
        yield {"db": db, "tenant": tenant, "customer": customer, "conversation": conversation}


def _receipt(route="live", reference="MF-ABCD2345") -> EscalationReceipt:
    return EscalationReceipt(
        reference=reference, route=route, reason="agent_available" if route == "live" else "no_agent_available",
        category="escalation",
    )


def _escalate(shop, text="I want a person", receipt=None):
    db, conversation = shop["db"], shop["conversation"]
    turn = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content=text, now=NOW)
    finish_turn(
        db, conversation_id=conversation.id, turn=turn, content="Passed to a person.", now=NOW,
        escalation=receipt or _receipt(),
    )


def _state(shop) -> Conversation:
    shop["db"].expire_all()
    return shop["db"].get(Conversation, shop["conversation"].id)


def test_an_escalation_puts_the_conversation_in_the_waiting_state_with_a_notice(shop):
    _escalate(shop)

    conversation = _state(shop)
    assert conversation.handoff_status == HandoffStatus.WAITING
    assert (conversation.escalation_reference, conversation.escalation_status) == ("MF-ABCD2345", "open")
    assert conversation.escalation_route == "live"
    assert conversation.handoff_requested_at is not None
    stored = list_messages(shop["db"], conversation_id=conversation.id)
    assert [(m.role, m.kind) for m in stored] == [("user", "text"), ("assistant", "text"), ("system", "system")]
    assert stored[1].reply_to_seq == 1
    assert stored[2].content == ESCALATION_NOTICE


def test_a_turn_that_does_not_escalate_does_not_wait_for_a_person(shop):
    db, conversation = shop["db"], shop["conversation"]
    turn = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content="hi", now=NOW)
    finish_turn(db, conversation_id=conversation.id, turn=turn, content="hello", now=NOW)
    assert _state(shop).handoff_status == HandoffStatus.NONE
    assert _state(shop).escalation_status is None


def test_an_offline_escalation_keeps_the_number_and_leaves_the_assistant_answering(shop):
    _escalate(shop, receipt=_receipt("offline"))

    conversation = _state(shop)
    assert (conversation.escalation_route, conversation.escalation_status) == ("offline", "open")
    assert conversation.escalation_reason == "no_agent_available"
    assert conversation.handoff_status == HandoffStatus.NONE
    assert [m.role for m in list_messages(shop["db"], conversation_id=conversation.id)] == ["user", "assistant"]
    db = shop["db"]
    next_turn = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content="and?", now=NOW)
    assert next_turn.action is TurnAction.RUN
    assert next_turn.open_escalation.reference == "MF-ABCD2345"


def test_insisting_keeps_the_open_number_and_a_resolved_one_is_replaced(shop):
    _escalate(shop, receipt=_receipt("offline", "MF-FIRST222"))
    _escalate(shop, receipt=_receipt("offline", "MF-SECOND33"))
    assert _state(shop).escalation_reference == "MF-FIRST222"

    shop["db"].query(Conversation).filter_by(id=shop["conversation"].id).update({"escalation_status": "resolved"})
    shop["db"].commit()
    _escalate(shop, receipt=_receipt("offline", "MF-THIRD444"))
    conversation = _state(shop)
    assert (conversation.escalation_reference, conversation.escalation_status) == ("MF-THIRD444", "open")
    assert [past["reference"] for past in conversation.escalation_history] == ["MF-FIRST222"]


def test_an_offline_escalation_that_becomes_live_keeps_its_number_and_waits_for_a_person(shop):
    _escalate(shop, receipt=_receipt("offline", "MF-FIRST222"))
    assert _state(shop).handoff_status == HandoffStatus.NONE

    _escalate(shop, receipt=_receipt("live", "MF-FIRST222"))

    conversation = _state(shop)
    assert (conversation.escalation_reference, conversation.escalation_route) == ("MF-FIRST222", "live")
    assert conversation.escalation_reason == "agent_available"
    assert conversation.handoff_status == HandoffStatus.WAITING


def test_while_a_person_has_the_conversation_a_message_is_stored_and_not_answered(shop):
    _escalate(shop)
    db, conversation = shop["db"], shop["conversation"]

    turn = begin_turn(db, conversation_id=conversation.id, client_message_id=uuid.uuid4(), content="hello?", now=NOW)

    assert (turn.action, turn.handoff) == (TurnAction.HANDOFF, HandoffStatus.WAITING)
    fresh = _state(shop)
    assert fresh.turn_id is None and fresh.turn_started_at is None
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


def test_a_chat_turn_that_escalates_live_leaves_the_conversation_waiting_for_a_person(shop, monkeypatch):
    final = {
        "messages": [HumanMessage(content="I want a person"), AIMessage(content="Passed to a person.")],
        "escalated": True,
        "escalation_receipt": _receipt(),
    }

    class Escalating(_Graph):
        async def astream_events(self, initial_state, config, version):
            yield {"event": "on_chain_end", "name": "LangGraph", "metadata": {}, "data": {"output": final}}

    monkeypatch.setattr(chat_module, "agent_graph", Escalating())

    client.post("/api/chat", json={"message": "I want a person", "message_id": str(uuid.uuid4())}, headers=_auth(shop))

    assert _state(shop).handoff_status == HandoffStatus.WAITING
    assert _state(shop).escalation_reference == "MF-ABCD2345"
