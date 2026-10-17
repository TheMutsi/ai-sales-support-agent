"""One-time-code (OTP) login: a visitor proves they own the email of one of a
tenant's customers, which gives the same standing as the shop vouching for them
(`otp_login`, a passwordless login).

What the *responses* say is flattened on purpose (timing still differs, and a limit
per IP is the real defence against probing; that isn't built yet):
- `request_otp` returns nothing whether or not the email belongs to a customer,
  and whether or not it was rate limited.
- `verify_otp` raises the same `invalid_code` for a wrong code, an expired one, a
  spent one, no challenge at all, and an unknown email.

Limits: valid 10 minutes, 5 wrong guesses kill a code, 5 sends per email per
hour. Tripping them is recorded as a `SecurityEvent` for review.

The code is stored only as an HMAC keyed with the server's secret: six digits are
a million possibilities, so a plain hash would be reversed instantly if the table leaked.

Not here yet: limits per IP, and flagging codes requested but never used.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.otp_sender import OtpSender
from app.db.models import Customer, OtpChallenge, SecurityEvent, Tenant

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 5


class OtpError(Exception):
    code = "invalid_code"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_code(key: str, challenge_id: uuid.UUID, code: str) -> str:
    return hmac.new(key.encode(), f"otp:{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _find_customer(db: Session, tenant: Tenant, email: str) -> Customer | None:
    matches = (
        db.query(Customer)
        .filter(Customer.tenant_id == tenant.id, func.lower(Customer.email) == email)
        .limit(2)
        .all()
    )
    # Two customers whose emails differ only by case are ambiguous: better to send
    # nothing than to guess who gets the code (or to fail with a 500 that gives it away).
    return matches[0] if len(matches) == 1 else None


def _record(db: Session, tenant: Tenant, kind: str, email: str) -> None:
    db.add(SecurityEvent(tenant_id=tenant.id, kind=kind, email=email))
    logger.warning("security event %s for %s (tenant %s)", kind, email, tenant.id)


def request_otp(
    db: Session, *, tenant: Tenant, email: str, sender: OtpSender, key: str, now: datetime
) -> None:
    email = normalize_email(email)
    if _find_customer(db, tenant, email) is None:
        return

    sent_last_hour = (
        db.query(OtpChallenge)
        .filter(
            OtpChallenge.tenant_id == tenant.id,
            OtpChallenge.email == email,
            OtpChallenge.created_at > now - timedelta(hours=1),
        )
        .count()
    )
    if sent_last_hour >= MAX_SENDS_PER_HOUR:
        _record(db, tenant, "otp_rate_limited", email)
        db.commit()
        return

    # A new code replaces any open one, so only the latest can be used.
    db.query(OtpChallenge).filter(
        OtpChallenge.tenant_id == tenant.id,
        OtpChallenge.email == email,
        OtpChallenge.consumed_at.is_(None),
        OtpChallenge.expires_at > now,
    ).update({"expires_at": now})

    code = f"{secrets.randbelow(10**6):06d}"
    challenge = OtpChallenge(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=email,
        created_at=now,
        expires_at=now + CODE_TTL,
        code_hash="",
    )
    challenge.code_hash = _hash_code(key, challenge.id, code)
    db.add(challenge)
    db.commit()
    try:
        sender.send(email=email, code=code)
    except Exception:
        logger.exception("could not deliver a one-time code (tenant %s)", tenant.id)


def verify_otp(
    db: Session, *, tenant: Tenant, email: str, code: str, key: str, now: datetime
) -> Customer:
    email = normalize_email(email)
    challenge = (
        db.query(OtpChallenge)
        .filter(
            OtpChallenge.tenant_id == tenant.id,
            OtpChallenge.email == email,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.expires_at > now,
            OtpChallenge.attempts < MAX_ATTEMPTS,
        )
        .order_by(OtpChallenge.created_at.desc())
        # Locks the row until commit: parallel guesses are counted one at a time, and
        # a correct code can only be consumed by one of them.
        .with_for_update()
        .first()
    )
    if challenge is None:
        raise OtpError

    if not hmac.compare_digest(challenge.code_hash, _hash_code(key, challenge.id, code)):
        challenge.attempts += 1
        if challenge.attempts >= MAX_ATTEMPTS:
            _record(db, tenant, "otp_max_attempts", email)
        db.commit()
        raise OtpError

    customer = _find_customer(db, tenant, email)
    if customer is None:
        # Commit, not rollback: it frees the row lock, and the session is the caller's, so
        # their pending work is not ours to discard.
        db.commit()
        raise OtpError
    challenge.consumed_at = now
    db.commit()
    return customer
