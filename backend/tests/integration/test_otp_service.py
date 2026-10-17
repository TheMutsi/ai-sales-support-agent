"""One-time-code login (`otp_login`): the code is never stored, dies after a few
wrong guesses, and an unknown email is indistinguishable from a wrong code."""

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.credentials import generate_api_key
from app.auth.otp import MAX_SENDS_PER_HOUR, request_otp
from app.db.models import Customer, OtpChallenge, SecurityEvent, Tenant
from app.db.session import SessionLocal

KEY = "k" * 32
EMAIL = "ana@shop.test"
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


class FakeSender:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, *, email: str, code: str) -> None:
        self.sent.append((email, code))

    @property
    def last_code(self) -> str:
        return self.sent[-1][1]


@pytest.fixture
def db(tenant_wipe):
    with SessionLocal() as session:
        yield session


@pytest.fixture
def tenant(db) -> Tenant:
    tenant = Tenant(name="Shop", api_key=generate_api_key())
    db.add(tenant)
    db.flush()
    db.add(Customer(name="Ana", email=EMAIL, tenant_id=tenant.id, external_id="c1"))
    db.commit()
    return tenant


def _request(db, tenant, sender, email=EMAIL, now=NOW):
    request_otp(db, tenant=tenant, email=email, sender=sender, key=KEY, now=now)


def test_a_six_digit_code_is_sent_and_never_stored(db, tenant):
    sender = FakeSender()

    _request(db, tenant, sender)

    assert [email for email, _ in sender.sent] == [EMAIL]
    code = sender.last_code
    assert len(code) == 6 and code.isdigit()
    challenge = db.query(OtpChallenge).one()
    assert code not in challenge.code_hash and challenge.code_hash != code


def test_an_unknown_email_sends_nothing_and_does_not_raise(db, tenant):
    sender = FakeSender()

    _request(db, tenant, sender, email="nobody@shop.test")

    assert sender.sent == []


def test_requests_beyond_the_hourly_limit_send_nothing_and_are_recorded(db, tenant):
    sender = FakeSender()
    for i in range(MAX_SENDS_PER_HOUR):
        _request(db, tenant, sender, now=NOW + timedelta(seconds=i))

    _request(db, tenant, sender, now=NOW + timedelta(minutes=30))

    assert len(sender.sent) == MAX_SENDS_PER_HOUR
    assert db.query(SecurityEvent).filter_by(kind="otp_rate_limited").count() == 1


def test_two_customers_whose_emails_differ_only_by_case_are_ambiguous_not_an_error(db, tenant):
    db.add(Customer(name="Ana 2", email="ANA@shop.test", tenant_id=tenant.id, external_id="c2"))
    db.commit()
    sender = FakeSender()

    _request(db, tenant, sender)  # must not raise

    assert sender.sent == []
