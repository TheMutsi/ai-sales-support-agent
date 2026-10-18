"""Every attempt to identify leaves a record a person can read: how (a code, here; an order and the
shop's login in the next change), what came of it and, for a failure, why. The reason stays in our database: the response
to the visitor is the same generic one as ever. Nothing in a record lets someone use it to get in:
no code, no full email, no order id, no token."""


import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_module
from app.auth import audit
from app.auth.credentials import generate_api_key
from app.core.config import get_settings
from app.db.models import Customer, IdentificationEvent, Tenant
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
        db.query(IdentificationEvent).delete()
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        customer = Customer(name="Ana", email=EMAIL, tenant_id=tenant.id, external_id="c1")
        db.add(customer)
        db.commit()
        yield {"tenant": tenant, "customer": customer, "api_key": tenant.api_key}
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


def test_an_unknown_api_key_leaves_no_record_because_there_is_no_shop_to_attribute_it_to(shop, sender):
    _request_code("pk_does_not_exist")
    with SessionLocal() as db:  # and the record itself refuses to write without a shop
        audit.record(
            db, key=get_settings().session_signing_key, tenant_id=None, method="order_id",
            outcome="failed", reason="unknown_key",
        )

    assert _events() == []


# --- what a record must never hold ------------------------------------------------------------


def test_no_record_holds_a_code_or_the_email(shop, sender):
    _request_code(shop["api_key"])
    _verify(shop["api_key"], sender.sent[0][1])
    _verify(shop["api_key"], "000000")

    secrets_ = [sender.sent[0][1], EMAIL, "ana"]
    for event in _events():
        stored = " ".join(str(v) for v in vars(event).values() if not str(v).startswith("<"))
        for secret in secrets_:
            assert secret not in stored, f"{secret!r} found in {event.method}/{event.outcome}"


# --- the audit never decides ---------------------------------------------------------------------


def test_a_failure_to_write_the_record_does_not_stop_a_login_and_is_logged(
    shop, sender, monkeypatch, caplog
):
    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "_write", broken)

    _request_code(shop["api_key"])
    code = sender.sent[0][1]
    with caplog.at_level("ERROR"):
        response = _verify(shop["api_key"], code)

    assert response.status_code == 200
    assert "identification audit" in caplog.text
