"""The session we issue in exchange for a shop's login token.

The shop's token is short-lived and only used for the login exchange (nothing
stops it being replayed within its lifetime); this is the longer-lived
credential the chat actually carries, so the shop is only asked for a fresh
token when the session runs out (about once a day), not on every message.
It records who the visitor is and *how* they were identified (`lvl`), because
the scopes that follow depend on the route.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.auth.scopes import IdentityLevel


def issue_session_token(
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    level: IdentityLevel,
    signing_key: str,
    ttl: timedelta,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + ttl
    claims = {
        "tid": str(tenant_id),
        "conv": str(conversation_id),
        "lvl": level.value,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if customer_id is not None:  # an anonymous session has no customer
        claims["cid"] = str(customer_id)
    return jwt.encode(claims, signing_key, algorithm="HS256"), expires_at


class SessionError(Exception):
    """`session_expired` is renewable (log in again); `invalid_session` is not."""

    def __init__(self, code: Literal["session_expired", "invalid_session"]):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SessionClaims:
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID | None  # None exactly when the level is anonymous
    level: IdentityLevel


def verify_session_token(token: str, signing_key: str) -> SessionClaims:
    """Checks a session we issued. The algorithm is fixed here, never read from
    the token, so `alg: none` can't skip the signature."""
    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["HS256"],
            options={"require": ["exp", "tid", "conv", "lvl"]},
        )
        level = IdentityLevel(claims["lvl"])
        # An anonymous session must not name a customer, and every other level must.
        if (level is IdentityLevel.ANONYMOUS) == ("cid" in claims):
            raise ValueError("customer claim inconsistent with the identity level")
        return SessionClaims(
            tenant_id=uuid.UUID(claims["tid"]),
            conversation_id=uuid.UUID(claims["conv"]),
            customer_id=uuid.UUID(claims["cid"]) if "cid" in claims else None,
            level=level,
        )
    except jwt.ExpiredSignatureError:
        raise SessionError("session_expired") from None
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise SessionError("invalid_session") from None
