import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.audit import mask_email
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
    return matches[0] if len(matches) == 1 else None


def _record(db: Session, tenant: Tenant, kind: str, email: str) -> None:
    db.add(SecurityEvent(tenant_id=tenant.id, kind=kind, email=email))
    logger.warning("security event %s for %s (tenant %s)", kind, mask_email(email), tenant.id)


def request_otp(
    db: Session, *, tenant: Tenant, email: str, sender: OtpSender, key: str, now: datetime
) -> str:
    email = normalize_email(email)
    if _find_customer(db, tenant, email) is None:
        return "unknown_customer"

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
        return "rate_limited"

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
    return "sent"


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
        db.commit()
        raise OtpError
    challenge.consumed_at = now
    db.commit()
    return customer
