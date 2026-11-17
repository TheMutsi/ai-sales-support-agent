import hashlib
import hmac
import logging
import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import IdentificationEvent

logger = logging.getLogger(__name__)


def mask_email(email: str) -> str:
    local, _, domain = email.strip().partition("@")
    name, _, tld = domain.rpartition(".")
    return f"{local[:1].lower()}***@{name[:1].lower()}***.{tld.lower()}"


def hmac_value(key: str, kind: str, value: str) -> str:
    normalized = value.strip().lower() if kind == "email" else value.strip()
    return hmac.new(key.encode(), f"audit:{kind}:{normalized}".encode(), hashlib.sha256).hexdigest()


def _write(db: Session, event: IdentificationEvent) -> None:
    db.add(event)
    db.commit()


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    method: str,
    outcome: str,
    reason: str | None = None,
    email: str | None = None,
    order_id: str | None = None,
    customer_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    if tenant_id is None:
        return
    try:
        key = get_settings().audit_key
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
