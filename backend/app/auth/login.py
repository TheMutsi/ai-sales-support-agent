"""Starting conversations and exchanging a shop's signed token for a session.

Kept separate from the routers so the decision logic is plain Python over a DB
session. Failures raise `LoginError` with a stable code and HTTP status:

- `invalid_token` (401) covers an unknown API key *and* a bad signature alike, so
  the *response* doesn't say which API keys exist. Response timing still differs
  (an unknown key skips the secrets lookup), so the per-IP rate limit on these endpoints
  (`app.api.rate_limit`) is the real defence against probing.
- `token_expired` (401) is its own code: the widget can fix it by asking the
  shop's server for a fresh token.
- `customer_not_found` (403) means the token was genuine but the shop's
  customer isn't known to us. We never create customers from a login, so a
  valid signature alone can't mint one.

A shop's token isn't single-use: it can be replayed until it expires (at most
an hour, see `MAX_TOKEN_LIFETIME_SECONDS`), and each replay mints a fresh session.
Enforcing one-time use would need a `jti` claim and a store of spent ones.

Every session belongs to a conversation. Starting one is anonymous; logging in
continues the conversation the caller presents (if it's usable) and attaches the
customer to it, or starts an identified one.
"""

import hmac
import uuid
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
            db, key=session_key, tenant_id=tenant.id, method="store_login", outcome="failed",
            reason=reason, conversation_id=conversation_id,
        )
        return LoginError(code, status_code)

    active_secrets = db.query(TenantSecret).filter_by(tenant_id=tenant.id, active=True).all()
    try:
        claims = verify_store_token(token, {s.kid: s.secret for s in active_secrets})
    except StoreTokenError as exc:
        raise failed(exc.code, exc.code, 401) from None

    customer = (
        db.query(Customer).filter_by(tenant_id=tenant.id, external_id=claims.sub).one_or_none()
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
        db, key=session_key, tenant_id=tenant.id, method="store_login", outcome="succeeded",
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
    sender: OtpSender,
    key: str,
    conversation_id: uuid.UUID | None = None,
) -> None:
    """Sends a code if the email is a customer's. Returns nothing in every case, an unknown
    API key included, so the response never says what exists. What happened goes to the audit
    record only."""
    tenant = db.query(Tenant).filter_by(api_key=api_key).one_or_none()
    if tenant is None:
        return
    result = request_otp(db, tenant=tenant, email=email, sender=sender, key=key, now=datetime.now(UTC))
    audit.record(
        db, key=key, tenant_id=tenant.id, method="otp",
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
            db, key=session_key, tenant_id=tenant.id, method="otp", outcome="failed",
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
        db, key=session_key, tenant_id=tenant.id, method="otp", outcome="succeeded", email=email,
        customer_id=customer.id, conversation_id=conversation.id,
    )
    return _session_response(
        tenant, conversation, level, session_key=session_key, session_ttl=session_ttl
    )


def find_tenant_id(db: Session, api_key: str) -> uuid.UUID | None:
    """The tenant an API key belongs to, so the shop's orders can be asked for *its* order."""
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
    """The visitor gave an email and an order id; `order` is what the shop's orders answered
    for that id (None if there is none). The email must be the order's: that comparison is
    ours, so it holds whoever provides the orders. Every failure is the same 401 (an unknown
    key, an unknown order, another shop's order, someone else's email), so the response never
    says which orders exist. The per-IP rate limit is the defence against probing.

    The session names the order and nothing else: the customer behind it is not attached, so
    an order id, which leaks easily, can never open the account."""
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
            db, key=session_key, tenant_id=tenant.id if tenant else None, method="order_id",
            outcome="failed", reason=reason, email=email, order_id=order_id,
            conversation_id=conversation_id,
        )
        raise LoginError("invalid_order_lookup", 401)
    conversation = resolve_for_order_lookup(
        db, tenant_id=tenant.id, conversation_id=conversation_id, now=datetime.now(UTC)
    )
    audit.record(
        db, key=session_key, tenant_id=tenant.id, method="order_id", outcome="succeeded",
        email=email, order_id=order.order_id, conversation_id=conversation.id,
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
    """Case-insensitive, and in constant time: the comparison does not leak how much matched."""
    return hmac.compare_digest(given.strip().casefold().encode(), expected.strip().casefold().encode())
