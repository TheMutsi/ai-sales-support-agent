"""The back office's session: a signed token naming a role (and, except for the operator, the
one tenant it is bound to).

While the login is a placeholder (ADR-0016) anyone can ask for any role, which is why the admin
API is mounted only in local environments. The token shares the signing key with the chat's
sessions and cannot be mistaken for one: it carries `kind: admin` and none of the `tid`/`conv`/`lvl`
claims a chat session requires, and the other way round.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.admin.permissions import Role


class AdminSessionError(Exception):
    """`session_expired`: log in again. `invalid_session`: cannot be fixed by retrying."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AdminSession:
    role: Role
    tenant_id: uuid.UUID | None
    name: str  # what a visitor sees when this person joins a chat


def issue_admin_token(
    *, role: Role, tenant_id: uuid.UUID | None, signing_key: str, ttl: timedelta, name: str
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + ttl
    claims = {
        "kind": "admin",
        "role": role.value,
        "name": name,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if tenant_id is not None:
        claims["ten"] = str(tenant_id)
    return jwt.encode(claims, signing_key, algorithm="HS256"), expires_at


def verify_admin_token(token: str, signing_key: str) -> AdminSession:
    try:
        claims = jwt.decode(
            token, signing_key, algorithms=["HS256"], options={"require": ["exp", "kind", "role", "name"]}
        )
        if claims["kind"] != "admin":
            raise ValueError("not an admin session")
        return AdminSession(
            role=Role(claims["role"]),
            name=str(claims["name"]),
            tenant_id=uuid.UUID(claims["ten"]) if "ten" in claims else None,
        )
    except jwt.ExpiredSignatureError:
        raise AdminSessionError("session_expired") from None
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise AdminSessionError("invalid_session") from None
