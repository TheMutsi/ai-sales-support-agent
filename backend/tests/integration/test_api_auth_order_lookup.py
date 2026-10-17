"""`POST /api/auth/order-lookup` through the real app: a visitor gets a weak session by giving
the email of an order and its id. The session names that one order, never the customer."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_order_source
from app.api.chat import _open_turn
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token, verify_session_token
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Order, Plan, Tenant
from app.db.session import SessionLocal, engine
from app.main import app
from app.schemas.chat import ChatRequest
from app.schemas.orders import OrderDetails, OrderStatus

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


def _a_valid_order() -> OrderDetails:
    return OrderDetails(
        order_id=ORDER_ID,
        customer_email=EMAIL,
        plan_slug="starter",
        amount_cents=2900,
        currency="usd",
        status=OrderStatus.PAID,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def fake_orders():
    """Replaces the shop's orders API with one the test controls, restoring the real one."""

    def install(source):
        app.dependency_overrides[get_order_source] = lambda: source

    yield install
    app.dependency_overrides.pop(get_order_source, None)


def test_the_twenty_first_attempt_in_an_hour_is_refused_whatever_it_gave(shop):
    statuses = [_lookup(shop["api_key"], email="mallory@shop.test").status_code for _ in range(21)]

    assert statuses[:20] == [401] * 20 and statuses[20] == 429


def test_a_conversation_of_another_shop_is_not_continued(shop):
    other_tenant_id = next(
        t.id for t in _all_tenants() if t.id != shop["tenant"].id
    )
    with SessionLocal() as db:
        foreign = Conversation(
            id=uuid.uuid4(),
            tenant_id=other_tenant_id,
            created_at=datetime.now(UTC),
            last_activity_at=datetime.now(UTC),
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    token, _ = issue_session_token(
        tenant_id=other_tenant_id,
        conversation_id=foreign_id,
        customer_id=None,
        level=IdentityLevel.ANONYMOUS,
        signing_key=get_settings().session_signing_key,
        ttl=timedelta(hours=1),
    )

    response = _lookup(shop["api_key"], headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["conversation_id"] != str(foreign_id)
    with SessionLocal() as db:
        assert db.get(Conversation, foreign_id).identity_level == "anonymous"


def _all_tenants():
    with SessionLocal() as db:
        return db.query(Tenant).all()


def test_the_session_it_gives_can_open_a_chat_turn(shop):
    """It has no customer, like an anonymous one: the chat must accept it as it does that."""
    response = _lookup(shop["api_key"])
    claims = verify_session_token(response.json()["session_token"], get_settings().session_signing_key)

    turn = _open_turn(claims, ChatRequest(message="hello", message_id=uuid.uuid4()))

    assert turn.user_text == "hello"


def test_no_database_connection_is_held_while_waiting_for_the_shops_orders(shop, fake_orders):
    """The orders will be a network call: the request's own session must not sit on a pooled
    connection (and its transaction) while it waits, or a slow shop drains the pool."""
    seen = {}

    class Source:
        async def get_order(self, *, tenant_id, order_id):
            seen["checked_out"] = engine.pool.checkedout()
            return _a_valid_order()

    fake_orders(Source())

    assert _lookup(shop["api_key"]).status_code == 200
    assert seen["checked_out"] == 0


@pytest.mark.asyncio
async def test_slow_orders_do_not_make_requests_wait_for_each_other(shop, fake_orders):
    """Five lookups against a source that takes 0.3 s each finish in about 0.3 s, not 1.5 s:
    the endpoint awaits instead of blocking the event loop."""

    class Slow:
        async def get_order(self, *, tenant_id, order_id):
            await asyncio.sleep(0.3)
            return _a_valid_order()

    fake_orders(Slow())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        started = time.perf_counter()
        responses = await asyncio.gather(
            *[
                http.post(
                    "/api/auth/order-lookup",
                    json={"api_key": shop["api_key"], "email": EMAIL, "order_id": ORDER_ID},
                )
                for _ in range(5)
            ]
        )
        elapsed = time.perf_counter() - started

    assert [r.status_code for r in responses] == [200] * 5
    assert elapsed < 1.2, f"requests were serialized: {elapsed:.2f}s"

