"""Exchanges a shop's signed token for one of our sessions (`store_login`).

A shop's token isn't single-use: it can be replayed until it expires (at most
an hour, see `MAX_TOKEN_LIFETIME_SECONDS`), and each replay mints a fresh session.
Enforcing one-time use would need a `jti` claim and a store of spent ones.

Kept separate from the router so the decision logic is plain Python over a DB
session. Failures raise `LoginError` with a stable code and HTTP status:

- `invalid_token` (401) covers an unknown API key *and* a bad signature alike, so
  the *response* doesn't say which API keys exist. Response timing still differs
  (an unknown key skips the secrets lookup), so rate limiting on this endpoint is
  the real defence against probing; that's not built yet.
- `token_expired` (401) is its own code: the widget can fix it by asking the
  shop's server for a fresh token.
- `customer_not_found` (403) means the token was genuine but the shop's
  customer isn't known to us. We never create customers from a login, so a
  valid signature alone can't mint one.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.auth.scopes import IdentityLevel, Scope, scopes_for
from app.auth.session import issue_session_token
from app.auth.store_token import StoreTokenError, verify_store_token
from app.db.models import Customer, Tenant, TenantSecret
from app.schemas.auth import LoginResponse


@dataclass
class LoginError(Exception):
    code: str
    status_code: int


def login_with_store_token(
    db: Session, *, api_key: str, token: str, session_key: str, session_ttl: timedelta
) -> LoginResponse:
    tenant = db.query(Tenant).filter_by(api_key=api_key).one_or_none()
    if tenant is None:
        raise LoginError("invalid_token", 401)

    active_secrets = (
        db.query(TenantSecret).filter_by(tenant_id=tenant.id, active=True).all()
    )
    try:
        claims = verify_store_token(token, {s.kid: s.secret for s in active_secrets})
    except StoreTokenError as exc:
        raise LoginError(exc.code, 401) from None

    customer = (
        db.query(Customer).filter_by(tenant_id=tenant.id, external_id=claims.sub).one_or_none()
    )
    if customer is None:
        raise LoginError("customer_not_found", 403)

    level = IdentityLevel.STORE_LOGIN
    session_token, expires_at = issue_session_token(
        tenant_id=tenant.id,
        customer_id=customer.id,
        level=level,
        signing_key=session_key,
        ttl=session_ttl,
    )
    scopes: list[Scope] = sorted(scopes_for(level, tenant.scope_overrides))
    return LoginResponse(
        session_token=session_token,
        expires_at=expires_at,
        identity_level=level,
        scopes=scopes,
    )
