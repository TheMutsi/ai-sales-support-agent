"""`POST /api/auth/otp/request` and `/verify` through the real app: a visitor gets a
session by proving they own a customer's email. The code is read from the sender,
never from a response."""

import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_module
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Tenant
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
EMAIL = "ana@shop.test"


class FakeSender:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, *, email: str, code: str) -> None:
        self.sent.append((email, code))


@pytest.fixture
def sender(monkeypatch):
    fake = FakeSender()
    monkeypatch.setattr(auth_module, "get_otp_sender", lambda settings: fake)
    return fake


@pytest.fixture
def shop(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        customer = Customer(name="Ana", email=EMAIL, tenant_id=tenant.id, external_id="c1")
        db.add(customer)
        db.commit()
        yield {"tenant": tenant, "customer": customer, "api_key": tenant.api_key}


def _request(api_key, email=EMAIL):
    return client.post("/api/auth/otp/request", json={"api_key": api_key, "email": email})


def _verify(api_key, code, email=EMAIL, headers=None):
    return client.post(
        "/api/auth/otp/verify",
        json={"api_key": api_key, "email": email, "code": code},
        headers=headers,
    )


def test_the_code_is_sent_and_the_response_does_not_contain_it(shop, sender):
    response = _request(shop["api_key"])

    assert response.status_code == 202
    code = sender.sent[0][1]
    assert code not in response.text


@pytest.mark.parametrize("email", ["nobody@shop.test", "not-an-email-but-fine"])
def test_an_unknown_email_gets_the_same_response_and_no_code(shop, sender, email):
    response = _request(shop["api_key"], email)

    assert response.status_code == 202 and response.content == _request(shop["api_key"]).content
    assert [sent_to for sent_to, _ in sender.sent] == [EMAIL]


def test_an_unknown_api_key_gets_the_same_response_as_a_known_one(shop, sender):
    response = _request("pk_does_not_exist")

    assert response.status_code == 202
    assert sender.sent == []


def test_the_right_code_gives_an_otp_login_session_for_that_customer(shop, sender):
    _request(shop["api_key"])

    response = _verify(shop["api_key"], sender.sent[0][1])

    assert response.status_code == 200
    body = response.json()
    assert body["identity_level"] == "otp_login"
    assert "customer:read" in body["scopes"]
    claims = jwt.decode(
        body["session_token"], get_settings().session_signing_key, algorithms=["HS256"]
    )
    assert claims["cid"] == str(shop["customer"].id) and claims["lvl"] == "otp_login"


@pytest.mark.parametrize("code", ["000000", "abc", ""])
def test_a_wrong_code_is_one_generic_401(shop, sender, code):
    _request(shop["api_key"])

    response = _verify(shop["api_key"], code)

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "invalid_code"}


def test_an_unknown_api_key_or_email_fails_like_a_wrong_code(shop, sender):
    _request(shop["api_key"])
    code = sender.sent[0][1]

    for response in (
        _verify("pk_does_not_exist", code),
        _verify(shop["api_key"], code, email="nobody@shop.test"),
    ):
        assert response.status_code == 401
        assert response.json()["detail"] == {"code": "invalid_code"}


def test_a_code_cannot_be_used_twice(shop, sender):
    _request(shop["api_key"])
    code = sender.sent[0][1]

    assert _verify(shop["api_key"], code).status_code == 200
    assert _verify(shop["api_key"], code).status_code == 401


def test_verifying_inside_an_anonymous_conversation_keeps_its_history(shop, sender):
    started = client.post("/api/conversations", json={"api_key": shop["api_key"]}).json()
    anonymous = {"Authorization": f"Bearer {started['session_token']}"}
    _request(shop["api_key"])

    response = _verify(shop["api_key"], sender.sent[0][1], headers=anonymous)

    assert response.json()["conversation_id"] == started["conversation_id"]
    with SessionLocal() as db:
        conversation = db.get(Conversation, uuid.UUID(started["conversation_id"]))
        assert conversation.customer_id == shop["customer"].id
        assert conversation.linked_via == IdentityLevel.OTP_LOGIN.value
