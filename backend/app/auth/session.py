"""The session we issue in exchange for a shop's login token.

The shop's token is short-lived and only used for the login exchange (nothing
stops it being replayed within its lifetime); this is the longer-lived
credential the chat actually carries, so the shop is only asked for a fresh
token when the session runs out (about once a day), not on every message.
It records who the visitor is and *how* they were identified (`lvl`), because
the scopes that follow depend on the route.
"""

import uuid
from datetime import UTC, datetime, timedelta

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
