"""`POST /api/conversations` starts an anonymous conversation, and logging in from it
attaches the customer to the same conversation (history carries over)."""

import time
import uuid
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.credentials import generate_api_key, generate_secret
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Tenant, TenantSecret
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


@pytest.fixture
def shop(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        secret = generate_secret()
        db.add(tenant)
        db.flush()
        db.add(TenantSecret(tenant_id=tenant.id, kid="k1", secret=secret))
        db.add(Customer(name="Ana", email="ana@shop.test", tenant_id=tenant.id, external_id="c1"))
        db.commit()
        yield {"api_key": tenant.api_key, "tenant_id": tenant.id, "secret": secret}


def _decode(session_token: str) -> dict:
    return jwt.decode(session_token, get_settings().session_signing_key, algorithms=["HS256"])


def _store_token(secret: str, sub: str = "c1") -> str:
    return jwt.encode({"sub": sub, "exp": int(time.time()) + 300}, secret, algorithm="HS256")


def _start(api_key: str):
    return client.post("/api/conversations", json={"api_key": api_key})


def _login(shop, headers=None):
    return client.post(
        "/api/auth/login",
        json={"api_key": shop["api_key"], "token": _store_token(shop["secret"])},
        headers=headers or {},
    )


def _bearer(session_token: str) -> dict:
    return {"Authorization": f"Bearer {session_token}"}


def test_starting_a_conversation_returns_an_anonymous_session(shop):
    response = _start(shop["api_key"])

    assert response.status_code == 200
    body = response.json()
    assert body["identity_level"] == "anonymous" and body["scopes"] == ["kb:read"]
    claims = _decode(body["session_token"])
    assert claims["conv"] == body["conversation_id"] and "cid" not in claims
    with SessionLocal() as db:
        conversation = db.get(Conversation, uuid.UUID(body["conversation_id"]))
        assert conversation.tenant_id == shop["tenant_id"] and conversation.customer_id is None


def test_an_unknown_api_key_cannot_start_a_conversation(shop):
    response = _start("pk_nope")

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "invalid_token"}


def test_logging_in_from_an_anonymous_session_keeps_the_conversation(shop):
    anonymous = _start(shop["api_key"]).json()

    response = _login(shop, _bearer(anonymous["session_token"]))

    body = response.json()
    assert body["conversation_id"] == anonymous["conversation_id"]
    assert body["identity_level"] == "store_login"
    assert "cid" in _decode(body["session_token"])
    with SessionLocal() as db:
        conversation = db.get(Conversation, uuid.UUID(body["conversation_id"]))
        assert conversation.customer_id is not None and conversation.linked_via == "store_login"


def test_logging_in_with_no_session_starts_an_identified_conversation(shop):
    body = _login(shop).json()

    with SessionLocal() as db:
        conversation = db.get(Conversation, uuid.UUID(body["conversation_id"]))
        assert conversation.customer_id is not None


@pytest.mark.parametrize("kind", ["expired", "garbage"])
def test_an_unusable_session_just_starts_a_new_conversation(shop, kind):
    expired, _ = issue_session_token(
        tenant_id=shop["tenant_id"],
        conversation_id=uuid.uuid4(),
        customer_id=None,
        level=IdentityLevel.ANONYMOUS,
        signing_key=get_settings().session_signing_key,
        ttl=timedelta(seconds=-120),
    )

    response = _login(shop, _bearer({"expired": expired, "garbage": "not-a-jwt"}[kind]))

    assert response.status_code == 200
    assert response.json()["identity_level"] == "store_login"


def test_a_session_from_another_tenant_is_never_attached_to(shop):
    with SessionLocal() as db:
        other = Tenant(name="Other", api_key=generate_api_key())
        db.add(other)
        db.commit()
        other_key = other.api_key
    foreign = _start(other_key).json()

    body = _login(shop, _bearer(foreign["session_token"])).json()

    assert body["conversation_id"] != foreign["conversation_id"]
    with SessionLocal() as db:
        assert db.get(Conversation, uuid.UUID(foreign["conversation_id"])).customer_id is None


def test_chatting_with_an_anonymous_session_asks_for_identification(shop):
    anonymous = _start(shop["api_key"]).json()

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_bearer(anonymous["session_token"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "identity_required"}
