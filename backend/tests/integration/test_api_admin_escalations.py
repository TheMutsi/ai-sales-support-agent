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
from app.db.models import AgentPresence, Conversation, Customer, Message, Tenant
from app.db.session import SessionLocal

app = FastAPI()
app.include_router(chat_router, prefix="/api")
for router in ADMIN_ROUTERS:
    app.include_router(router, prefix="/api")
client = TestClient(app)
NOW = datetime.now(UTC)


def _conversation(
    db, tenant, customer, *, status, minutes_waiting, name=None, route="live", escalation="open",
    reference=None, category="escalation", tags=(), properties=None, said=None,
):
    """`status` is the handoff state; `escalation` the state of the escalation itself (None: none)."""
    conversation = Conversation(
        tenant_id=tenant.id, customer_id=customer.id, identity_level="store_login",
        created_at=NOW.replace(tzinfo=None), last_activity_at=NOW.replace(tzinfo=None),
        handoff_status=status, handoff_agent_name=name,
        handoff_requested_at=NOW - timedelta(minutes=minutes_waiting),
        escalation_reference=reference or f"MF-{uuid.uuid4().hex[:8].upper()}" if escalation else None,
        escalation_route=route if escalation else None, escalation_reason="agent_available" if escalation else None,
        escalation_category=category if escalation else None, escalation_status=escalation,
        escalated_at=NOW - timedelta(minutes=minutes_waiting) if escalation else None,
        tags=list(tags), properties=properties or {},
    )
    db.add(conversation)
    db.flush()
    if said:
        db.add(Message(conversation_id=conversation.id, seq=1, role="user", kind="text", content=said, created_at=NOW))
        conversation.last_seq = 1
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
        waiting_new = _conversation(db, a, ana, status="waiting", minutes_waiting=1, said="my parcel never came")
        waiting_old = _conversation(db, a, ana, status="waiting", minutes_waiting=30, tags=["vip"])
        active = _conversation(db, a, ana, status="active", minutes_waiting=60, name="Lucía")
        _conversation(db, a, ana, status="none", minutes_waiting=90, escalation=None)
        offline = _conversation(
            db, a, ana, status="none", minutes_waiting=120, route="offline", reference="MF-OFFLINE22",
            category="refund", tags=["vip", "black-friday"], properties={"device": "iphone"},
        )
        resolved = _conversation(
            db, a, ana, status="none", minutes_waiting=300, route="offline", escalation="resolved", said="refund please",
        )
        other = _conversation(db, b, bob, status="waiting", minutes_waiting=5)
        db.commit()
        yield {
            "a": a, "ana": ana, "new": waiting_new.id, "old": waiting_old.id, "active": active.id,
            "offline": offline.id, "resolved": resolved.id, "other": other.id,
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


def _ids(world, **params) -> list[str]:
    response = client.get(_url(world, None), params=params, headers=_login("viewer", world["a"].id))
    assert response.status_code == 200
    return [item["id"] for item in response.json()]


def test_the_inbox_lists_who_waits_longest_first_then_who_is_being_helped_then_the_offline_ones(world):
    items = client.get(_url(world, None), headers=_login("viewer", world["a"].id)).json()
    assert [(i["id"], i["route"], i["handoff_status"]) for i in items] == [
        (str(world["old"]), "live", "waiting"), (str(world["new"]), "live", "waiting"),
        (str(world["active"]), "live", "active"), (str(world["offline"]), "offline", "none"),
    ]
    assert items[0]["customer"]["email_masked"] == "a***@a***.test"
    assert items[0]["reference"].startswith("MF-") and items[0]["tags"] == ["vip"]
    assert items[2]["agent_name"] == "Lucía"
    assert str(world["other"]) not in str(items) and str(world["resolved"]) not in str(items)


def test_the_resolved_ones_are_listed_on_request_after_the_open_ones(world):
    ids = _ids(world, status="all")
    assert ids[-1] == str(world["resolved"]) and len(ids) == 5
    assert _ids(world, status="resolved") == [str(world["resolved"])]


def test_the_search_filters_by_route_category_tag_and_property(world):
    assert _ids(world, route="offline") == [str(world["offline"])]
    assert _ids(world, category="refund") == [str(world["offline"])]
    assert _ids(world, tag="vip") == [str(world["old"]), str(world["offline"])]
    assert _ids(world, tag=["vip", "black-friday"]) == [str(world["offline"])]  # every tag
    assert _ids(world, property="device:iphone") == [str(world["offline"])]
    assert _ids(world, property="device:android") == []
    assert client.get(_url(world, None), params={"property": "nokey"}, headers=_login("viewer", world["a"].id)).status_code == 422


def test_the_search_text_looks_in_the_number_the_customer_and_what_they_said(world):
    assert _ids(world, q="MF-OFFLINE22") == [str(world["offline"])]
    assert _ids(world, q="mf-offline") == [str(world["offline"])]  # case does not matter
    assert _ids(world, q="parcel") == [str(world["new"])]
    assert len(_ids(world, q="ana@a.test")) == 4  # every open one of that customer
    assert _ids(world, q="refund", status="all") == [str(world["resolved"])]
    assert _ids(world, q="no such thing") == []
    assert _ids(world, q="%") == []  # a wildcard is just a character
    assert _ids(world, q="parcel", route="offline") == []  # filters narrow together


def test_the_search_filters_by_when_it_was_escalated(world):
    since = (NOW - timedelta(minutes=100)).isoformat()
    assert _ids(world, since=since) == [str(world["old"]), str(world["new"]), str(world["active"])]
    assert _ids(world, until=since) == [str(world["offline"])]


def test_the_inbox_can_be_paged(world):
    first = _ids(world, limit=2)
    assert first == [str(world["old"]), str(world["new"])]
    assert _ids(world, limit=2, offset=2) == [str(world["active"]), str(world["offline"])]


def test_looking_at_the_inbox_as_someone_who_can_answer_makes_them_available_but_a_viewer_does_not(world):
    from app.chat.presence import count_available

    client.get(_url(world, None), headers=_login("viewer", world["a"].id))
    with SessionLocal() as db:
        assert count_available(db, tenant_id=world["a"].id, now=datetime.now(UTC)) == 0
    client.get(_url(world, None), headers=_login("agent", world["a"].id, name="Mónica"))
    with SessionLocal() as db:
        assert count_available(db, tenant_id=world["a"].id, now=datetime.now(UTC)) == 1
        assert db.query(AgentPresence).one().agent_name == "Mónica"


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
    assert (conversation.escalation_status, conversation.escalation_notes) == ("resolved", "sorted out")
    assert conversation.escalation_resolved_by == "Mónica"
    with SessionLocal() as db:
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
        none = db.query(Conversation).filter_by(tenant_id=world["a"].id, escalation_status=None).one().id
    agent = _login("agent", world["a"].id)
    for action, body in (("claim", None), ("close", {}), ("resolve", {})):
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


def test_a_blank_name_falls_back_to_the_role(world):
    blank = client.post("/api/admin/session", json={"role": "agent", "tenant_id": str(world["a"].id), "name": "   "})
    assert blank.json()["name"] == "Agent"


def test_closing_a_chat_nobody_joined_does_not_say_someone_left(world):
    agent = _login("agent", world["a"].id, name="Mónica")
    assert client.post(_url(world, world["old"], "close"), json={}, headers=agent).status_code == 204
    visitor = _visitor(world, world["old"])
    last = client.get(f"/api/conversations/{world['old']}/messages", headers=visitor).json()["messages"][-1]
    assert (last["kind"], last["content"]) == ("system", "The assistant is back.")


def test_an_offline_escalation_is_resolved_with_a_note_and_only_once(world):
    agent = _login("agent", world["a"].id, name="Mónica")
    resolved = client.post(_url(world, world["offline"], "resolve"), json={"notes": "refund sent"}, headers=agent)
    assert resolved.status_code == 204
    conversation = _state(world["offline"])
    assert (conversation.escalation_status, conversation.escalation_notes) == ("resolved", "refund sent")
    assert conversation.escalation_resolved_by == "Mónica"
    again = client.post(_url(world, world["offline"], "resolve"), json={}, headers=agent)
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "not_open")
    assert str(world["offline"]) not in str(client.get(_url(world, None), headers=agent).json())


def test_a_live_escalation_is_closed_not_resolved_and_a_viewer_cannot_resolve(world):
    agent = _login("agent", world["a"].id)
    assert client.post(_url(world, world["old"], "resolve"), json={}, headers=agent).status_code == 409
    viewer = _login("viewer", world["a"].id)
    assert client.post(_url(world, world["offline"], "resolve"), json={}, headers=viewer).status_code == 403
    assert _state(world["offline"]).escalation_status == "open"
