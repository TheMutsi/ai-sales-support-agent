"""What every admin route depends on: the session, and the permission a route declares.

Kept apart from the routes so the route modules can share it without importing each other.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.admin.permissions import ROLE_PERMISSIONS, Permission, can_access_tenant
from app.admin.session import AdminSession, AdminSessionError, verify_admin_token
from app.core.config import get_settings


def error(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def admin_session(authorization: Annotated[str | None, Header()] = None) -> AdminSession:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise error(401, "missing_session")
    try:
        return verify_admin_token(token.strip(), get_settings().session_signing_key)
    except AdminSessionError as exc:
        raise error(401, exc.code) from None


def require_permission(permission: Permission):
    """A dependency that lets through a session whose role holds `permission`."""

    def check(session: Annotated[AdminSession, Depends(admin_session)]) -> AdminSession:
        if permission not in ROLE_PERMISSIONS[session.role]:
            raise error(403, "forbidden")
        return session

    check.permission = permission  # type: ignore[attr-defined]  # read by the route-coverage test
    return check


def require_tenant_permission(permission: Permission):
    """`require_permission` for routes about one tenant (`{tenant_id}` in the path): the session
    must also be allowed to see that tenant."""

    def check(
        tenant_id: uuid.UUID,
        session: Annotated[AdminSession, Depends(require_permission(permission))],
    ) -> AdminSession:
        if not can_access_tenant(session.role, session.tenant_id, tenant_id):
            raise error(403, "wrong_tenant")
        return session

    check.permission = permission  # type: ignore[attr-defined]
    return check
