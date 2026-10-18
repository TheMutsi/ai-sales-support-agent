"""The record of every attempt to identify (`IdentificationEvent`).

A person reading it can tell how someone tried to identify, whether it worked and, for a failure,
why. What it keeps is chosen so the table is of no use to someone who reads it: the email is masked
(`a***@n***.com`) and hashed with a key (to group attempts by the same address), an order id is
only hashed, and a code or a token is never passed in at all.

Writing it never decides a login: if the write fails the attempt carries on and the failure is
logged, because an outage of the audit store must not lock every customer out.
"""

import hashlib
import hmac
import logging
import uuid

from sqlalchemy.orm import Session

from app.db.models import IdentificationEvent

logger = logging.getLogger(__name__)


def mask_email(email: str) -> str:
    """`ava.chen@northlight.com` -> `a***@n***.com`: enough to recognise, not to reuse."""
    local, _, domain = email.strip().partition("@")
    name, _, tld = domain.rpartition(".")
    return f"{local[:1].lower()}***@{name[:1].lower()}***.{tld.lower()}"


def hmac_value(key: str, kind: str, value: str) -> str:
    """A keyed hash that groups equal values and hides them. `kind` separates what is hashed (an
    email and an order id never collide) and emails are normalized like the rest of the login."""
    normalized = value.strip().lower() if kind == "email" else value.strip()
    return hmac.new(key.encode(), f"audit:{kind}:{normalized}".encode(), hashlib.sha256).hexdigest()


def _write(db: Session, event: IdentificationEvent) -> None:
    db.add(event)
    db.commit()


def record(
    db: Session,
    *,
    key: str,
    tenant_id: uuid.UUID | None,
    method: str,
    outcome: str,
    reason: str | None = None,
    email: str | None = None,
    order_id: str | None = None,
    customer_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    """Records one attempt. Without a tenant there is no shop to attribute it to (an unknown API
    key), so nothing is written.

    It commits the caller's session, and a failed write rolls it back, so the caller must have
    committed whatever it needs before calling (every current caller has). Anything pending would
    be lost with the rollback."""
    if tenant_id is None:
        return
    try:
        _write(
            db,
            IdentificationEvent(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                customer_id=customer_id,
                method=method,
                outcome=outcome,
                reason=reason,
                email_masked=mask_email(email) if email else None,
                email_hmac=hmac_value(key, "email", email) if email else None,
                order_hmac=hmac_value(key, "order", order_id) if order_id else None,
            ),
        )
    except Exception:
        db.rollback()
        logger.exception("identification audit could not be written (method=%s)", method)
