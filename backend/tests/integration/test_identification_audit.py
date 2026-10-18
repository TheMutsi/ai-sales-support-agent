"""Every attempt to identify leaves a record a person can read: how (a code, an order, the shop's
login), what came of it and, for a failure, why. The reason stays in our database: the response
to the visitor is the same generic one as ever. Nothing in a record lets someone use it to get in:
no code, no full email, no order id, no token."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_module
from app.auth import audit
from app.auth.credentials import generate_api_key, generate_secret
from app.core.config import get_settings
from app.db.models import Customer, IdentificationEvent, Order, Plan, Tenant, TenantSecret
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
EMAIL = "ana@shop.test"
ORDER_ID = "A1b2C3d4E5f6G7h8I9j0"


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
        db.query(IdentificationEvent).delete()
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        secret = generate_secret()
        db.add(tenant)
        db.flush()
        db.add(TenantSecret(tenant_id=tenant.id, kid="k1", secret=secret))
        customer = Customer(name="Ana", email=EMAIL, tenant_id=tenant.id, external_id="c1")
        plan = Plan(slug="starter", name="Starter", price_cents=2900, billing_period="monthly")
        db.add_all([customer, plan])
        db.flush()
        db.add(Order(order_id=ORDER_ID, customer_id=customer.id, plan_id=plan.id, amount_cents=2900))
        db.commit()
        yield {"tenant": tenant, "customer": customer, "secret": secret, "api_key": tenant.api_key}
        db.query(IdentificationEvent).delete()
        db.commit()


def _events() -> list[IdentificationEvent]:
    with SessionLocal() as db:
        return db.query(IdentificationEvent).order_by(IdentificationEvent.created_at).all()


def _only_event() -> IdentificationEvent:
    [event] = _events()
    return event


def _request_code(api_key, email=EMAIL, headers=None):
    return client.post("/api/auth/otp/request", json={"api_key": api_key, "email": email}, headers=headers)


def _verify(api_key, code, headers=None):
    return client.post(
        "/api/auth/otp/verify", json={"api_key": api_key, "email": EMAIL, "code": code}, headers=headers
    )


def _lookup(api_key, order_id=ORDER_ID, email=EMAIL, headers=None):
    return client.post(
        "/api/auth/order-lookup",
        json={"api_key": api_key, "email": email, "order_id": order_id},
        headers=headers,
    )


def _store_login(api_key, token):
    return client.post("/api/auth/login", json={"api_key": api_key, "token": token})


def _store_token(secret, **claims):
    return jwt.encode({"sub": "c1", "exp": int(time.time()) + 300, **claims}, secret, algorithm="HS256")


# --- one-time codes ----------------------------------------------------------------------------


def test_asking_for_a_code_is_recorded_with_the_email_masked_and_hashed(shop, sender):
    _request_code(shop["api_key"])

    event = _only_event()
    assert (event.method, event.outcome) == ("otp", "code_sent")
    assert event.tenant_id == shop["tenant"].id
    assert event.email_masked == "a***@s***.test"
    assert event.email_hmac == audit.hmac_value(get_settings().session_signing_key, "email", EMAIL)


def test_asking_for_a_code_for_an_unknown_email_is_recorded_as_failed_and_looks_the_same_outside(
    shop, sender
):
    known = _request_code(shop["api_key"])
    unknown = _request_code(shop["api_key"], "nobody@shop.test")

    assert known.status_code == unknown.status_code == 202 and known.content == unknown.content
    sent, failed = _events()
    assert (sent.outcome, failed.outcome, failed.reason) == ("code_sent", "failed", "unknown_customer")


def test_a_code_request_that_carries_a_session_is_tied_to_its_conversation(shop, sender):
    started = client.post("/api/conversations", json={"api_key": shop["api_key"]}).json()

    _request_code(shop["api_key"], headers={"Authorization": f"Bearer {started['session_token']}"})

    assert str(_only_event().conversation_id) == started["conversation_id"]


def test_the_right_code_is_recorded_as_a_success_for_that_customer_and_conversation(shop, sender):
    started = client.post("/api/conversations", json={"api_key": shop["api_key"]}).json()
    headers = {"Authorization": f"Bearer {started['session_token']}"}
    _request_code(shop["api_key"])

    response = _verify(shop["api_key"], sender.sent[0][1], headers=headers)

    assert response.status_code == 200
    event = _events()[-1]
    assert (event.method, event.outcome, event.reason) == ("otp", "succeeded", None)
    assert event.customer_id == shop["customer"].id
    assert str(event.conversation_id) == started["conversation_id"]


def test_a_wrong_code_is_recorded_with_its_reason_and_the_visitor_only_gets_the_generic_401(
    shop, sender
):
    _request_code(shop["api_key"])

    response = _verify(shop["api_key"], "000000")

    assert response.status_code == 401 and response.json() == {"detail": {"code": "invalid_code"}}
    event = _events()[-1]
    assert (event.method, event.outcome, event.reason) == ("otp", "failed", "invalid_code")


# --- an order -----------------------------------------------------------------------------------


def test_a_matching_order_is_recorded_without_the_order_id(shop):
    started = client.post("/api/conversations", json={"api_key": shop["api_key"]}).json()

    _lookup(shop["api_key"], headers={"Authorization": f"Bearer {started['session_token']}"})

    event = _only_event()
    assert (event.method, event.outcome) == ("order_id", "succeeded")
    assert event.email_masked == "a***@s***.test"
    assert event.order_hmac == audit.hmac_value(get_settings().session_signing_key, "order", ORDER_ID)
    assert str(event.conversation_id) == started["conversation_id"]
    assert event.customer_id is None, "an order proves one order, not the customer"


@pytest.mark.parametrize(
    ("order_id", "email", "reason"),
    [("n" * 20, EMAIL, "order_not_found"), (ORDER_ID, "mallory@shop.test", "email_mismatch")],
)
def test_a_failed_order_lookup_records_why_but_answers_with_one_generic_401(shop, order_id, email, reason):
    response = _lookup(shop["api_key"], order_id=order_id, email=email)

    assert response.status_code == 401 and response.json() == {"detail": {"code": "invalid_order_lookup"}}
    event = _only_event()
    assert (event.method, event.outcome, event.reason) == ("order_id", "failed", reason)


# --- the shop's own login -------------------------------------------------------------------------


def test_the_shops_login_is_recorded_as_a_success_and_as_failures_with_their_reasons(shop):
    assert _store_login(shop["api_key"], _store_token(shop["secret"])).status_code == 200
    assert _store_login(shop["api_key"], _store_token(shop["secret"], sub="ghost")).status_code == 403
    assert _store_login(shop["api_key"], _store_token(shop["secret"], exp=1)).status_code == 401

    ok, ghost, expired = _events()
    assert (ok.method, ok.outcome, ok.customer_id) == ("store_login", "succeeded", shop["customer"].id)
    assert (ghost.outcome, ghost.reason) == ("failed", "customer_not_found")
    assert (expired.outcome, expired.reason) == ("failed", "token_expired")


def test_an_unknown_api_key_leaves_no_record_because_there_is_no_shop_to_attribute_it_to(shop):
    _lookup("pk_does_not_exist")
    _request_code("pk_does_not_exist")

    assert _events() == []


# --- what a record must never hold ------------------------------------------------------------


def test_no_record_holds_a_code_the_email_an_order_id_or_a_token(shop, sender):
    """Every outcome of every method, successes and failures: a failure path that stored what the
    visitor typed would otherwise go unnoticed."""
    _request_code(shop["api_key"])
    _verify(shop["api_key"], sender.sent[0][1])
    _verify(shop["api_key"], "000000")
    _request_code(shop["api_key"], "mallory@shop.test")
    _lookup(shop["api_key"])
    _lookup(shop["api_key"], email="mallory@shop.test")
    _lookup(shop["api_key"], order_id="n" * 20)
    token = _store_token(shop["secret"])
    _store_login(shop["api_key"], token)
    expired = _store_token(shop["secret"], exp=1)
    _store_login(shop["api_key"], expired)
    _store_login(shop["api_key"], _store_token(shop["secret"], sub="ghost"))

    secrets_ = [
        sender.sent[0][1], EMAIL, "ana", "mallory", ORDER_ID, "n" * 20, token, expired, shop["secret"],
    ]
    events = _events()
    assert {(e.method, e.outcome) for e in events} >= {
        ("otp", "code_sent"), ("otp", "succeeded"), ("otp", "failed"),
        ("order_id", "succeeded"), ("order_id", "failed"),
        ("store_login", "succeeded"), ("store_login", "failed"),
    }
    for event in events:
        stored = " ".join(str(v) for v in vars(event).values() if not str(v).startswith("<"))
        for secret in secrets_:
            assert secret not in stored, f"{secret!r} found in {event.method}/{event.outcome}"


def test_an_order_is_grouped_by_what_the_visitor_typed_whatever_the_shop_calls_it(shop):
    """The shop may return its own spelling of an id (case, a prefix); the failure path can only
    hash what was typed, so the success path must too or one order would get two hashes."""
    from datetime import UTC, datetime, timedelta

    from app.auth.login import login_with_order
    from app.schemas.orders import OrderDetails, OrderStatus

    canonical = OrderDetails(
        order_id="A" * 20, customer_email=EMAIL, plan_slug="starter", amount_cents=2900,
        currency="usd", status=OrderStatus.PAID, created_at=datetime.now(UTC),
    )
    with SessionLocal() as db:
        login_with_order(
            db, api_key=shop["api_key"], email=EMAIL, order_id="a" * 20, order=canonical,
            conversation_id=None, session_key=get_settings().session_signing_key,
            session_ttl=timedelta(hours=1),
        )

    assert _only_event().order_hmac == audit.hmac_value(
        get_settings().session_signing_key, "order", "a" * 20
    )


# --- the audit never decides ---------------------------------------------------------------------


def test_a_failure_to_write_the_record_does_not_stop_a_login_and_is_logged(shop, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "_write", broken)

    with caplog.at_level("ERROR"):
        response = _lookup(shop["api_key"])

    assert response.status_code == 200
    assert "identification audit" in caplog.text


def test_a_failure_while_building_the_record_does_not_stop_a_login_either(shop, monkeypatch, caplog):
    def broken(email):
        raise ValueError("odd input")

    monkeypatch.setattr(audit, "mask_email", broken)

    with caplog.at_level("ERROR"):
        response = _lookup(shop["api_key"])

    assert response.status_code == 200
    assert "identification audit" in caplog.text

