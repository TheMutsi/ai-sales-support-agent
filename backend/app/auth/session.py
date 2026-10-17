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
    customer_id: uuid.UUID,
    level: IdentityLevel,
    signing_key: str,
    ttl: timedelta,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + ttl
    claims = {
        "tid": str(tenant_id),
        "cid": str(customer_id),
        "lvl": level.value,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, signing_key, algorithm="HS256"), expires_at


class SessionError(Exception):
    """`session_expired` is renewable (log in again); `invalid_session` is not."""

    def __init__(self, code: Literal["session_expired", "invalid_session"]):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SessionClaims:
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    level: IdentityLevel


def verify_session_token(token: str, signing_key: str) -> SessionClaims:
    """Checks a session we issued. The algorithm is fixed here, never read from
    the token, so `alg: none` can't skip the signature."""
    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["HS256"],
            options={"require": ["exp", "tid", "cid", "lvl"]},
        )
        return SessionClaims(
            tenant_id=uuid.UUID(claims["tid"]),
            customer_id=uuid.UUID(claims["cid"]),
            level=IdentityLevel(claims["lvl"]),
        )
    except jwt.ExpiredSignatureError:
        raise SessionError("session_expired") from None
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise SessionError("invalid_session") from None
