"""The conversation viewer against a real Postgres: what is shown, and to whom."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import ADMIN_ROUTERS
from app.auth.credentials import generate_api_key
from app.db.models import Conversation, Customer, IdentificationEvent, Message, Tenant
from app.db.session import SessionLocal

app = FastAPI()
for router in ADMIN_ROUTERS:
    app.include_router(router, prefix="/api")
client = TestClient(app)
NOW = datetime.now(UTC).replace(tzinfo=None)


def _conversation(db, tenant, *, minutes_ago, customer=None, texts=()):
    conversation = Conversation(
        tenant_id=tenant.id,
        customer_id=customer.id if customer else None,
        identity_level="store_login" if customer else "anonymous",
        linked_via="store_login" if customer else None,
        created_at=NOW - timedelta(minutes=minutes_ago + 5),
        last_activity_at=NOW - timedelta(minutes=minutes_ago),
        last_seq=len(texts),
    )
    db.add(conversation)
    db.flush()
    for seq, text in enumerate(texts, start=1):
        db.add(
            Message(
                conversation_id=conversation.id,
                seq=seq,
                role="user" if seq % 2 else "assistant",
                content=text,
                created_at=datetime.now(UTC),
            )
        )
    return conversation


@pytest.fixture
def world(tenant_wipe):
    with SessionLocal() as db:
        a = Tenant(name="Shop A", api_key=generate_api_key())
        b = Tenant(name="Shop B", api_key=generate_api_key())
        db.add_all([a, b])
        db.flush()
        ana = Customer(name="Ana Gómez", email="ana.gomez@shop-a.test", tenant_id=a.id)
        db.add(ana)
        db.flush()
        old = _conversation(db, a, minutes_ago=60, texts=["Hello?", "Hi!"])
        recent = _conversation(db, a, minutes_ago=1, customer=ana, texts=["Where is my order? " + "x" * 300, "Checking."])
        db.add(
            IdentificationEvent(
                tenant_id=a.id,
                conversation_id=recent.id,
                method="store_login",
                outcome="succeeded",
                email_masked="a***@s***.test",
            )
        )
        other = _conversation(db, b, minutes_ago=5, texts=["secret of shop B"])
        db.commit()
        return {"a": str(a.id), "b": str(b.id), "old": str(old.id), "recent": str(recent.id), "other": str(other.id)}


def _login(role, tenant_id=None):
    body = client.post("/api/admin/session", json={"role": role, "tenant_id": tenant_id}).json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_the_list_is_newest_first_with_a_preview_and_a_masked_customer(world):
    items = client.get(f"/api/admin/tenants/{world['a']}/conversations", headers=_login("viewer", world["a"])).json()
    assert [i["id"] for i in items] == [world["recent"], world["old"]]
    assert items[0]["customer"] == {"name": "Ana Gómez", "email_masked": "a***@s***.test"}
    assert len(items[0]["first_message"]) == 120
    assert items[1]["customer"] is None
    assert items[0]["message_count"] == 2
    assert "ana.gomez@shop-a.test" not in str(items)


def test_the_list_pages_by_last_activity(world):
    headers, url = _login("viewer", world["a"]), f"/api/admin/tenants/{world['a']}/conversations"
    first = client.get(url, params={"limit": 1}, headers=headers).json()
    assert [i["id"] for i in first] == [world["recent"]]
    second = client.get(url, params={"limit": 1, "before": first[0]["last_activity_at"]}, headers=headers).json()
    assert [i["id"] for i in second] == [world["old"]]


def test_the_list_never_shows_another_tenants_conversations(world):
    items = client.get(f"/api/admin/tenants/{world['a']}/conversations", headers=_login("operator")).json()
    assert world["other"] not in [i["id"] for i in items]


def test_the_detail_has_messages_in_order_and_the_identification_timeline(world):
    detail = client.get(
        f"/api/admin/tenants/{world['a']}/conversations/{world['recent']}", headers=_login("viewer", world["a"])
    ).json()
    assert [m["seq"] for m in detail["messages"]] == [1, 2]
    assert detail["messages"][1]["role"] == "assistant"
    assert detail["linked_via"] == "store_login"
    assert [(e["method"], e["outcome"]) for e in detail["identification"]] == [("store_login", "succeeded")]


def test_another_tenants_conversation_is_not_found_even_for_its_neighbour(world):
    # Asking for B's conversation under A's id must not reveal it, whoever asks.
    for headers in (_login("viewer", world["a"]), _login("operator")):
        response = client.get(f"/api/admin/tenants/{world['a']}/conversations/{world['other']}", headers=headers)
        assert (response.status_code, response.json()["detail"]["code"]) == (404, "conversation_not_found")


def test_a_tenant_bound_session_cannot_read_another_tenants_conversations(world):
    headers = _login("admin", world["a"])
    assert client.get(f"/api/admin/tenants/{world['b']}/conversations", headers=headers).status_code == 403
    assert client.get(
        f"/api/admin/tenants/{world['b']}/conversations/{world['other']}", headers=headers
    ).status_code == 403


def test_it_needs_a_session_and_validates_the_page_size(world):
    url = f"/api/admin/tenants/{world['a']}/conversations"
    assert client.get(url).status_code == 401
    assert client.get(url, params={"limit": 0}, headers=_login("viewer", world["a"])).status_code == 422
    assert client.get(url, params={"limit": 101}, headers=_login("viewer", world["a"])).status_code == 422


def test_an_unknown_conversation_is_not_found(world):
    response = client.get(
        f"/api/admin/tenants/{world['a']}/conversations/{uuid.uuid4()}", headers=_login("viewer", world["a"])
    )
    assert response.status_code == 404
