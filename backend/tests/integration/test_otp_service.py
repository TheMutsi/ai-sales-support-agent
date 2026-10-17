"""One-time-code login (`otp_login`): the code is never stored, dies after a few
wrong guesses, and an unknown email is indistinguishable from a wrong code."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.auth import otp as otp_module
from app.auth.credentials import generate_api_key
from app.auth.otp import (
    CODE_TTL,
    MAX_ATTEMPTS,
    MAX_SENDS_PER_HOUR,
    OtpError,
    request_otp,
    verify_otp,
)
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


def _verify(db, tenant, code, email=EMAIL, now=NOW):
    return verify_otp(db, tenant=tenant, email=email, code=code, key=KEY, now=now)


def test_a_six_digit_code_is_sent_and_never_stored(db, tenant):
    sender = FakeSender()

    _request(db, tenant, sender)

    assert [email for email, _ in sender.sent] == [EMAIL]
    code = sender.last_code
    assert len(code) == 6 and code.isdigit()
    challenge = db.query(OtpChallenge).one()
    assert code not in challenge.code_hash and challenge.code_hash != code


def test_the_right_code_returns_the_customer_and_works_only_once(db, tenant):
    sender = FakeSender()
    _request(db, tenant, sender)

    customer = _verify(db, tenant, sender.last_code)

    assert customer.email == EMAIL
    with pytest.raises(OtpError):
        _verify(db, tenant, sender.last_code)


def test_the_email_is_matched_ignoring_case_and_spaces(db, tenant):
    sender = FakeSender()
    _request(db, tenant, sender, email="  ANA@Shop.test ")

    assert _verify(db, tenant, sender.last_code, email="Ana@SHOP.test").email == EMAIL


def test_a_wrong_code_is_rejected(db, tenant):
    sender = FakeSender()
    _request(db, tenant, sender)
    wrong = "000000" if sender.last_code != "000000" else "111111"

    with pytest.raises(OtpError) as error:
        _verify(db, tenant, wrong)

    assert error.value.code == "invalid_code"


def test_the_code_dies_after_too_many_wrong_guesses_and_the_event_is_recorded(db, tenant):
    sender = FakeSender()
    _request(db, tenant, sender)
    wrong = "000000" if sender.last_code != "000000" else "111111"

    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(OtpError):
            _verify(db, tenant, wrong)

    with pytest.raises(OtpError):
        _verify(db, tenant, sender.last_code)  # even the right one is dead now
    events = db.query(SecurityEvent).filter_by(kind="otp_max_attempts").all()
    assert len(events) == 1 and events[0].email == EMAIL


def test_an_expired_code_is_rejected(db, tenant):
    sender = FakeSender()
    _request(db, tenant, sender)

    with pytest.raises(OtpError):
        _verify(db, tenant, sender.last_code, now=NOW + CODE_TTL + timedelta(seconds=1))


def test_requesting_a_new_code_invalidates_the_previous_one(db, tenant):
    sender = FakeSender()
    _request(db, tenant, sender)
    first = sender.last_code
    _request(db, tenant, sender, now=NOW + timedelta(minutes=1))
    assert len(sender.sent) == 2

    with pytest.raises(OtpError):
        _verify(db, tenant, first, now=NOW + timedelta(minutes=2))
    assert _verify(db, tenant, sender.last_code, now=NOW + timedelta(minutes=2)).email == EMAIL


def test_an_unknown_email_sends_nothing_and_fails_like_a_wrong_code(db, tenant):
    sender = FakeSender()

    _request(db, tenant, sender, email="nobody@shop.test")  # no error either way

    assert sender.sent == []
    with pytest.raises(OtpError) as error:
        _verify(db, tenant, "123456", email="nobody@shop.test")
    assert error.value.code == "invalid_code"


def test_requests_beyond_the_hourly_limit_send_nothing_and_are_recorded(db, tenant):
    sender = FakeSender()
    for i in range(MAX_SENDS_PER_HOUR):
        _request(db, tenant, sender, now=NOW + timedelta(seconds=i))

    _request(db, tenant, sender, now=NOW + timedelta(minutes=30))

    assert len(sender.sent) == MAX_SENDS_PER_HOUR
    assert db.query(SecurityEvent).filter_by(kind="otp_rate_limited").count() == 1


def test_a_code_cannot_be_used_against_another_tenant(db, tenant):
    other = Tenant(name="Other", api_key=generate_api_key())
    db.add(other)
    db.flush()
    db.add(Customer(name="Ana", email=EMAIL, tenant_id=other.id, external_id="c9"))
    db.commit()
    sender = FakeSender()
    _request(db, tenant, sender)

    with pytest.raises(OtpError):
        _verify(db, other, sender.last_code)


@pytest.fixture
def slow_compare(monkeypatch):
    """Widens the race window: every parallel request reads the challenge before
    any of them writes, so a missing lock fails the test every time, not 1 run in 6."""
    real = otp_module.hmac.compare_digest

    def slow(a, b):
        time.sleep(0.05)
        return real(a, b)

    monkeypatch.setattr(otp_module.hmac, "compare_digest", slow)


def _verify_in_its_own_session(tenant_id, code):
    """What a parallel request does: its own DB session, no shared state."""
    with SessionLocal() as session:
        try:
            verify_otp(
                session, tenant=session.get(Tenant, tenant_id), email=EMAIL, code=code, key=KEY,
                now=NOW,
            )
            return True
        except OtpError:
            return False


def test_parallel_requests_with_the_right_code_cannot_all_succeed(db, tenant, slow_compare):
    sender = FakeSender()
    _request(db, tenant, sender)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _verify_in_its_own_session(tenant.id, sender.last_code),
                                range(8)))

    assert results.count(True) == 1


def test_parallel_wrong_guesses_are_all_counted(db, tenant, slow_compare):
    """Without a lock, parallel guesses read the same attempt count and slip past the limit."""
    sender = FakeSender()
    _request(db, tenant, sender)
    wrong = "000000" if sender.last_code != "000000" else "111111"
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda _: _verify_in_its_own_session(tenant.id, wrong), range(20)))

    db.expire_all()
    assert db.query(OtpChallenge).one().attempts == MAX_ATTEMPTS


def test_two_customers_whose_emails_differ_only_by_case_are_ambiguous_not_an_error(db, tenant):
    db.add(Customer(name="Ana 2", email="ANA@shop.test", tenant_id=tenant.id, external_id="c2"))
    db.commit()
    sender = FakeSender()

    _request(db, tenant, sender)  # must not raise

    assert sender.sent == []


def test_a_customer_deleted_after_the_request_fails_without_holding_the_lock(db, tenant):
    sender = FakeSender()
    _request(db, tenant, sender)
    db.query(Customer).delete()
    db.commit()

    with pytest.raises(OtpError):
        _verify(db, tenant, sender.last_code)

    # The challenge row must be free for others, not left locked by the failed call.
    with SessionLocal() as other:
        other.execute(
            text("SELECT id FROM otp_challenges FOR UPDATE NOWAIT")
        ).all()


def test_a_failed_verification_does_not_discard_the_callers_pending_work(db, tenant):
    """The session belongs to the caller: rolling it back would silently drop their writes."""
    sender = FakeSender()
    _request(db, tenant, sender)
    db.query(Customer).delete()
    db.commit()
    db.add(SecurityEvent(tenant_id=tenant.id, kind="caller_work", email=EMAIL))

    with pytest.raises(OtpError):
        _verify(db, tenant, sender.last_code)

    with SessionLocal() as other:
        assert other.query(SecurityEvent).filter_by(kind="caller_work").count() == 1
