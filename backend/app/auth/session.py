import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.auth.scopes import IdentityLevel
from app.schemas.orders import is_valid_order_id


def issue_session_token(
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    level: IdentityLevel,
    signing_key: str,
    ttl: timedelta,
    order_id: str | None = None,
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
    if customer_id is not None:
        claims["cid"] = str(customer_id)
    if order_id is not None:
        claims["oid"] = order_id
    return jwt.encode(claims, signing_key, algorithm="HS256"), expires_at


class SessionError(Exception):
    def __init__(self, code: Literal["session_expired", "invalid_session"]):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SessionClaims:
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID | None
    level: IdentityLevel
    order_id: str | None = None


def verify_session_token(token: str, signing_key: str) -> SessionClaims:
    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["HS256"],
            options={"require": ["exp", "tid", "conv", "lvl"]},
        )
        level = IdentityLevel(claims["lvl"])
        names_customer = level in (IdentityLevel.STORE_LOGIN, IdentityLevel.OTP_LOGIN)
        names_order = level is IdentityLevel.ORDER_LOOKUP
        if ("cid" in claims) != names_customer or ("oid" in claims) != names_order:
            raise ValueError("identity claims inconsistent with the identity level")
        if names_order and not is_valid_order_id(claims["oid"]):
            raise ValueError("malformed order id")
        return SessionClaims(
            tenant_id=uuid.UUID(claims["tid"]),
            conversation_id=uuid.UUID(claims["conv"]),
            customer_id=uuid.UUID(claims["cid"]) if "cid" in claims else None,
            level=level,
            order_id=claims.get("oid"),
        )
    except jwt.ExpiredSignatureError:
        raise SessionError("session_expired") from None
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise SessionError("invalid_session") from None
