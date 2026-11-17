import hmac
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.auth import audit
from app.auth.conversations import create_anonymous, resolve_for_login, resolve_for_order_lookup
from app.auth.otp import OtpError, request_otp, verify_otp
from app.auth.otp_sender import OtpSender
from app.auth.scopes import IdentityLevel, scopes_for
from app.auth.session import issue_session_token
from app.auth.store_token import StoreTokenError, verify_store_token
from app.db.models import Conversation, Customer, Tenant, TenantSecret
from app.schemas.auth import SessionResponse
from app.schemas.orders import OrderDetails


@dataclass
class LoginError(Exception):
    code: str
    status_code: int


def _find_tenant(db: Session, api_key: str) -> Tenant:
    tenant = db.query(Tenant).filter_by(api_key=api_key).one_or_none()
    if tenant is None:
        raise LoginError("invalid_token", 401)
    return tenant


def _session_response(
    tenant: Tenant,
    conversation: Conversation,
    level: IdentityLevel,
    *,
    session_key: str,
    session_ttl: timedelta,
    order_id: str | None = None,
) -> SessionResponse:
    session_token, expires_at = issue_session_token(
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        customer_id=conversation.customer_id,
        level=level,
        signing_key=session_key,
        ttl=session_ttl,
        order_id=order_id,
    )
    return SessionResponse(
        session_token=session_token,
        conversation_id=conversation.id,
        expires_at=expires_at,
        identity_level=level,
        scopes=sorted(scopes_for(level, tenant.scope_overrides)),
    )


def start_conversation(
    db: Session, *, api_key: str, session_key: str, session_ttl: timedelta
) -> SessionResponse:
    tenant = _find_tenant(db, api_key)
    conversation = create_anonymous(db, tenant_id=tenant.id, now=datetime.now(UTC))
    return _session_response(
        tenant, conversation, IdentityLevel.ANONYMOUS, session_key=session_key,
        session_ttl=session_ttl,
    )


def login_with_store_token(
    db: Session,
    *,
    api_key: str,
    token: str,
    conversation_id: uuid.UUID | None,
    session_key: str,
    session_ttl: timedelta,
) -> SessionResponse:
    tenant = _find_tenant(db, api_key)

    def failed(reason: str, code: str, status_code: int) -> LoginError:
        audit.record(
            db, tenant_id=tenant.id, method="store_login", outcome="failed",
            reason=reason, conversation_id=conversation_id,
        )
        return LoginError(code, status_code)

    active_secrets = db.query(TenantSecret).filter_by(tenant_id=tenant.id, active=True).all()
    try:
        claims = verify_store_token(token, {s.kid: s.secret for s in active_secrets})
    except StoreTokenError as exc:
        raise failed(exc.code, exc.code, 401) from None

    customer = (
        db.query(Customer).filter_by(tenant_id=tenant.id, external_id=claims.customer_external_id).one_or_none()
    )
    if customer is None:
        raise failed("customer_not_found", "customer_not_found", 403)

    level = IdentityLevel.STORE_LOGIN
    conversation = resolve_for_login(
        db,
        tenant_id=tenant.id,
        customer_id=customer.id,
        level=level,
        conversation_id=conversation_id,
        now=datetime.now(UTC),
    )
    audit.record(
        db, tenant_id=tenant.id, method="store_login", outcome="succeeded",
        customer_id=customer.id, conversation_id=conversation.id,
    )
    return _session_response(
        tenant, conversation, level, session_key=session_key, session_ttl=session_ttl
    )


def send_otp(
    db: Session,
    *,
    api_key: str,
    email: str,
    sender_for: Callable[[Tenant], OtpSender],
    key: str,
    conversation_id: uuid.UUID | None = None,
) -> None:
    tenant = db.query(Tenant).filter_by(api_key=api_key).one_or_none()
    if tenant is None:
        return
    result = request_otp(
        db, tenant=tenant, email=email, sender=sender_for(tenant), key=key, now=datetime.now(UTC)
    )
    audit.record(
        db, tenant_id=tenant.id, method="otp",
        outcome="code_sent" if result == "sent" else "failed",
        reason=None if result == "sent" else result, email=email, conversation_id=conversation_id,
    )


def login_with_otp(
    db: Session,
    *,
    api_key: str,
    email: str,
    code: str,
    conversation_id: uuid.UUID | None,
    session_key: str,
    session_ttl: timedelta,
) -> SessionResponse:
    tenant = db.query(Tenant).filter_by(api_key=api_key).one_or_none()
    if tenant is None:
        raise OtpError
    now = datetime.now(UTC)
    try:
        customer = verify_otp(db, tenant=tenant, email=email, code=code, key=session_key, now=now)
    except OtpError as exc:
        audit.record(
            db, tenant_id=tenant.id, method="otp", outcome="failed",
            reason=exc.code, email=email, conversation_id=conversation_id,
        )
        raise
    level = IdentityLevel.OTP_LOGIN
    conversation = resolve_for_login(
        db,
        tenant_id=tenant.id,
        customer_id=customer.id,
        level=level,
        conversation_id=conversation_id,
        now=now,
    )
    audit.record(
        db, tenant_id=tenant.id, method="otp", outcome="succeeded", email=email,
        customer_id=customer.id, conversation_id=conversation.id,
    )
    return _session_response(
        tenant, conversation, level, session_key=session_key, session_ttl=session_ttl
    )


def find_tenant_id(db: Session, api_key: str) -> uuid.UUID | None:
    tenant = db.query(Tenant).filter_by(api_key=api_key).one_or_none()
    return tenant.id if tenant else None


def login_with_order(
    db: Session,
    *,
    api_key: str,
    email: str,
    order_id: str,
    order: OrderDetails | None,
    conversation_id: uuid.UUID | None,
    session_key: str,
    session_ttl: timedelta,
) -> SessionResponse:
    tenant = db.query(Tenant).filter_by(api_key=api_key).one_or_none()
    reason = (
        "unknown_key"
        if tenant is None
        else "order_not_found"
        if order is None
        else None
        if _same_email(email, order.customer_email)
        else "email_mismatch"
    )
    if reason is not None:
        audit.record(
            db, tenant_id=tenant.id if tenant else None, method="order_id",
            outcome="failed", reason=reason, email=email, order_id=order_id,
            conversation_id=conversation_id,
        )
        raise LoginError("invalid_order_lookup", 401)
    conversation = resolve_for_order_lookup(
        db, tenant_id=tenant.id, conversation_id=conversation_id, now=datetime.now(UTC)
    )
    audit.record(
        db, tenant_id=tenant.id, method="order_id", outcome="succeeded",
        email=email, order_id=order_id, conversation_id=conversation.id,
    )
    return _session_response(
        tenant,
        conversation,
        IdentityLevel.ORDER_LOOKUP,
        session_key=session_key,
        session_ttl=session_ttl,
        order_id=order.order_id,
    )


def _same_email(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.strip().casefold().encode(), expected.strip().casefold().encode())
