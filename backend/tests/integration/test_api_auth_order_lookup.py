"""`POST /api/auth/order-lookup` through the real app: a visitor gets a weak session by giving
the email of an order and its id. The session names that one order, never the customer."""

import uuid
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Order, Plan, Tenant
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
EMAIL = "ana@shop.test"
ORDER_ID = "A1b2C3d4E5f6G7h8I9j0"
OTHER_ORDER_ID = "Z9y8X7w6V5u4T3s2R1q0"


def _tenant_with_order(db, *, name, email, order_id, plan):
    tenant = Tenant(name=name, api_key=generate_api_key())
    db.add(tenant)
    db.flush()
    customer = Customer(name="Ana", email=email, tenant_id=tenant.id, external_id=name)
    db.add(customer)
    db.flush()
    db.add(Order(order_id=order_id, customer_id=customer.id, plan_id=plan.id, amount_cents=2900))
    db.commit()
    return tenant, customer


@pytest.fixture
def shop(tenant_wipe):
    with SessionLocal() as db:
        plan = Plan(slug="starter", name="Starter", price_cents=2900, billing_period="monthly")
        db.add(plan)
        db.flush()
        tenant, customer = _tenant_with_order(
            db, name="Shop", email=EMAIL, order_id=ORDER_ID, plan=plan
        )
        # Another shop with an order of its own: its id must never resolve for the first.
        _tenant_with_order(
            db, name="Other", email="bob@other.test", order_id=OTHER_ORDER_ID, plan=plan
        )
        yield {"tenant": tenant, "customer": customer, "api_key": tenant.api_key}


def _lookup(api_key, order_id=ORDER_ID, email=EMAIL, headers=None):
    return client.post(
        "/api/auth/order-lookup",
        json={"api_key": api_key, "email": email, "order_id": order_id},
        headers=headers,
    )


def _claims(response):
    return jwt.decode(
        response.json()["session_token"], get_settings().session_signing_key, algorithms=["HS256"]
    )


def test_the_right_email_and_order_give_a_session_for_that_order_only(shop):
    response = _lookup(shop["api_key"])

    assert response.status_code == 200
    body = response.json()
    assert body["identity_level"] == "order_lookup"
    assert sorted(body["scopes"]) == ["kb:read", "order:read"]
    claims = _claims(response)
    assert claims["oid"] == ORDER_ID and claims["lvl"] == "order_lookup"
    assert "cid" not in claims, "an order id must never stand for the customer"


def test_the_email_is_compared_without_regard_to_case(shop):
    assert _lookup(shop["api_key"], email="ANA@Shop.Test").status_code == 200


def test_it_continues_the_callers_anonymous_conversation_without_attaching_a_customer(shop):
    start = client.post("/api/conversations", json={"api_key": shop["api_key"]}).json()

    response = _lookup(
        shop["api_key"], headers={"Authorization": f"Bearer {start['session_token']}"}
    )

    assert response.json()["conversation_id"] == start["conversation_id"]
    with SessionLocal() as db:
        conversation = db.get(Conversation, uuid.UUID(start["conversation_id"]))
        assert conversation.customer_id is None
        assert conversation.identity_level == "order_lookup"


def test_a_conversation_that_already_has_a_customer_is_not_reused(shop):
    with SessionLocal() as db:
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=shop["tenant"].id,
            customer_id=shop["customer"].id,
            identity_level="otp_login",
            created_at=shop["customer"].created_at,
            last_activity_at=shop["customer"].created_at,
        )
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id
    token, _ = issue_session_token(
        tenant_id=shop["tenant"].id,
        conversation_id=conversation_id,
        customer_id=shop["customer"].id,
        level=IdentityLevel.OTP_LOGIN,
        signing_key=get_settings().session_signing_key,
        ttl=timedelta(hours=1),
    )

    response = _lookup(shop["api_key"], headers={"Authorization": f"Bearer {token}"})

    assert response.json()["conversation_id"] != str(conversation_id)


@pytest.mark.parametrize(
    "case",
    ["wrong-email", "unknown-order", "another-shops-order", "unknown-key"],
)
def test_every_failure_is_the_same_401(shop, case):
    attempt = {
        "wrong-email": lambda: _lookup(shop["api_key"], email="mallory@shop.test"),
        "unknown-order": lambda: _lookup(shop["api_key"], order_id="n" * 20),
        "another-shops-order": lambda: _lookup(
            shop["api_key"], order_id=OTHER_ORDER_ID, email="bob@other.test"
        ),
        "unknown-key": lambda: _lookup("pk_does_not_exist"),
    }[case]
    reference = _lookup(shop["api_key"], email="mallory@shop.test")

    response = attempt()

    assert response.status_code == 401
    assert response.json() == reference.json() == {"detail": {"code": "invalid_order_lookup"}}


@pytest.mark.parametrize("order_id", ["", "short", "a" * 21, "a" * 19 + "\n", "é" * 20])
def test_a_malformed_order_id_is_rejected_before_anything_runs(shop, order_id):
    assert _lookup(shop["api_key"], order_id=order_id).status_code == 422


def test_a_malformed_email_is_rejected_before_anything_runs(shop):
    assert _lookup(shop["api_key"], email="not-an-email").status_code == 422
