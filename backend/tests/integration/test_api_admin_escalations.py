"""The back office's inbox of escalations: a person joins an escalated conversation, talks to the
visitor and gives it back to the assistant."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import ADMIN_ROUTERS
from app.api.chat import router as chat_router
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.chat.turns import TurnAction, begin_turn
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Tenant, Ticket
from app.db.session import SessionLocal

app = FastAPI()
app.include_router(chat_router, prefix="/api")
for router in ADMIN_ROUTERS:
    app.include_router(router, prefix="/api")
client = TestClient(app)
NOW = datetime.now(UTC)


def _conversation(db, tenant, customer, *, status, minutes_waiting, name=None):
    ticket = Ticket(customer_id=customer.id, category="escalation", subject="Wants a person", description="d")
    db.add(ticket)
    db.flush()
    conversation = Conversation(
        tenant_id=tenant.id, customer_id=customer.id, identity_level="store_login",
        created_at=NOW.replace(tzinfo=None), last_activity_at=NOW.replace(tzinfo=None),
        handoff_status=status, handoff_agent_name=name, handoff_ticket_id=ticket.id,
        handoff_requested_at=NOW - timedelta(minutes=minutes_waiting),
    )
    db.add(conversation)
    db.flush()
    return conversation


@pytest.fixture
def world(tenant_wipe):
    with SessionLocal() as db:
        a, b = Tenant(name="Shop A", api_key=generate_api_key()), Tenant(name="Shop B", api_key=generate_api_key())
        db.add_all([a, b])
        db.flush()
        ana = Customer(name="Ana", email="ana@a.test", tenant_id=a.id)
        bob = Customer(name="Bob", email="bob@b.test", tenant_id=b.id)
        db.add_all([ana, bob])
        db.flush()
        waiting_new = _conversation(db, a, ana, status="waiting", minutes_waiting=1)
        waiting_old = _conversation(db, a, ana, status="waiting", minutes_waiting=30)
        active = _conversation(db, a, ana, status="active", minutes_waiting=60, name="Lucía")
        _conversation(db, a, ana, status="none", minutes_waiting=90)
        other = _conversation(db, b, bob, status="waiting", minutes_waiting=5)
        db.commit()
        yield {
            "a": a, "ana": ana, "new": waiting_new.id, "old": waiting_old.id, "active": active.id,
            "other": other.id,
        }


def _login(role, tenant_id=None, name=None):
    body = client.post("/api/admin/session", json={"role": role, "tenant_id": str(tenant_id) if tenant_id else None, "name": name}).json()
    return {"Authorization": f"Bearer {body['token']}"}


def _url(world, conversation_id, action=""):
    return f"/api/admin/tenants/{world['a'].id}/escalations" + (f"/{conversation_id}/{action}" if action else "")


def _state(conversation_id) -> Conversation:
    with SessionLocal() as db:
        return db.get(Conversation, conversation_id)


def _visitor(world, conversation_id) -> dict:
    token, _ = issue_session_token(
        tenant_id=world["a"].id, conversation_id=conversation_id, customer_id=world["ana"].id,
        level=IdentityLevel.STORE_LOGIN, signing_key=get_settings().session_signing_key, ttl=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def test_the_inbox_lists_who_waits_longest_first_then_who_is_being_helped(world):
    items = client.get(_url(world, None), headers=_login("viewer", world["a"].id)).json()
    assert [(i["id"], i["handoff_status"]) for i in items] == [
        (str(world["old"]), "waiting"), (str(world["new"]), "waiting"), (str(world["active"]), "active"),
    ]
    assert items[0]["customer"]["email_masked"] == "a***@a***.test"
    assert items[0]["ticket"]["subject"] == "Wants a person"
    assert items[2]["agent_name"] == "Lucía"
    assert str(world["other"]) not in str(items)


def test_a_viewer_reads_the_inbox_but_cannot_act_on_it(world):
    headers = _login("viewer", world["a"].id)
    assert client.get(_url(world, None), headers=headers).status_code == 200
    for action in ("claim", "close"):
        assert client.post(_url(world, world["old"], action), json={}, headers=headers).status_code == 403
    assert client.post(_url(world, world["active"], "messages"), json={"text": "hi"}, headers=headers).status_code == 403
    assert _state(world["old"]).handoff_status == "waiting"


def test_an_agent_joins_talks_and_hands_the_conversation_back(world):
    agent = _login("agent", world["a"].id, name="Mónica")
    visitor = _visitor(world, world["old"])

    assert client.post(_url(world, world["old"], "messages"), json={"text": "too early"}, headers=agent).status_code == 409
    assert client.post(_url(world, world["old"], "claim"), headers=agent).status_code == 204
    assert client.post(_url(world, world["old"], "claim"), headers=agent).status_code == 409  # taken
    sent = client.post(_url(world, world["old"], "messages"), json={"text": "Hi, I am Mónica."}, headers=agent)
    assert (sent.status_code, sent.json()["author_name"]) == (200, "Mónica")

    seen = client.get(f"/api/conversations/{world['old']}/messages", headers=visitor).json()
    assert seen["handoff"] == "active"
    assert [(m["role"], m["kind"], m["content"], m["author_name"]) for m in seen["messages"]] == [
        ("system", "system", "Mónica joined the chat.", None),
        ("human", "text", "Hi, I am Mónica.", "Mónica"),
    ]

    closed = client.post(_url(world, world["old"], "close"), json={"notes": "sorted out"}, headers=agent)
    assert closed.status_code == 204
    conversation = _state(world["old"])
    assert (conversation.handoff_status, conversation.handoff_agent_name) == ("none", None)
    with SessionLocal() as db:
        ticket = db.get(Ticket, conversation.handoff_ticket_id)
        assert (ticket.status, ticket.resolution_notes) == ("resolved", "sorted out")
        # The assistant answers the visitor again.
        turn = begin_turn(db, conversation_id=world["old"], client_message_id=uuid.uuid4(), content="thanks", now=NOW)
        assert turn.action is TurnAction.RUN
    last = client.get(f"/api/conversations/{world['old']}/messages", headers=visitor).json()["messages"]
    assert last[-2]["content"] == "Mónica left the chat. The assistant is back."


def test_an_empty_reply_is_refused(world):
    agent = _login("agent", world["a"].id)
    response = client.post(_url(world, world["active"], "messages"), json={"text": ""}, headers=agent)
    assert response.status_code == 422


def test_nothing_can_be_done_to_a_conversation_that_is_not_in_a_handoff(world):
    with SessionLocal() as db:
        none = db.query(Conversation).filter_by(tenant_id=world["a"].id, handoff_status="none").one().id
    agent = _login("agent", world["a"].id)
    for action, body in (("claim", None), ("close", {})):
        assert client.post(_url(world, none, action), json=body, headers=agent).status_code == 409


def test_another_tenants_conversation_cannot_be_touched_even_by_the_operator_under_the_wrong_tenant(world):
    for headers in (_login("agent", world["a"].id), _login("operator")):
        for action in ("claim", "close"):
            response = client.post(_url(world, world["other"], action), json={}, headers=headers)
            assert (response.status_code, response.json()["detail"]["code"]) == (404, "conversation_not_found")
    assert _state(world["other"]).handoff_status == "waiting"


def test_a_session_of_another_tenant_cannot_use_this_inbox(world):
    other_agent = _login("agent", _state(world["other"]).tenant_id)
    assert client.get(_url(world, None), headers=other_agent).status_code == 403
    assert client.post(_url(world, world["old"], "claim"), headers=other_agent).status_code == 403


def test_the_name_defaults_to_the_role_and_is_limited(world):
    default = client.post("/api/admin/session", json={"role": "agent", "tenant_id": str(world["a"].id)}).json()
    assert default["name"] == "Agent"
    assert client.post("/api/admin/session", json={"role": "agent", "tenant_id": str(world["a"].id), "name": "x" * 41}).status_code == 422
