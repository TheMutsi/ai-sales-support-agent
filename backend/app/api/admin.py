"""The back office's API (`/api/admin`), mounted only in local environments (ADR-0016).

Every route except the placeholder login declares the permission it needs through
`require_permission` / `require_tenant_permission`; `tests/unit/test_admin_permissions.py` fails
if one does not, so a forgotten check fails a test instead of opening a route.
"""

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.permissions import (
    CROSS_TENANT_ROLES,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    can_access_tenant,
)
from app.admin.session import (
    AdminSession,
    AdminSessionError,
    issue_admin_token,
    verify_admin_token,
)
from app.auth.scopes import scope_override_problems
from app.core.config import get_settings
from app.core.origins import normalize_origin
from app.core.tenant_config import tenant_configs
from app.db.models import Tenant
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

_ADMIN_SESSION_TTL = timedelta(hours=8)


def _error(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def _admin_session(authorization: Annotated[str | None, Header()] = None) -> AdminSession:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _error(401, "missing_session")
    try:
        return verify_admin_token(token.strip(), get_settings().session_signing_key)
    except AdminSessionError as exc:
        raise _error(401, exc.code) from None


def require_permission(permission: Permission):
    """A dependency that lets through a session whose role holds `permission`."""

    def check(session: Annotated[AdminSession, Depends(_admin_session)]) -> AdminSession:
        if permission not in ROLE_PERMISSIONS[session.role]:
            raise _error(403, "forbidden")
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
            raise _error(403, "wrong_tenant")
        return session

    check.permission = permission  # type: ignore[attr-defined]
    return check


class AdminLoginRequest(BaseModel):
    role: Role
    tenant_id: uuid.UUID | None = None  # required for every role but the operator


class AdminLoginResponse(BaseModel):
    token: str
    role: Role
    tenant_id: uuid.UUID | None
    expires_at: datetime
    permissions: list[Permission]


@router.post("/session", response_model=AdminLoginResponse)
def placeholder_login(
    request: AdminLoginRequest, db: Annotated[Session, Depends(get_db)]
) -> AdminLoginResponse:
    """No authentication: anyone may ask for any role. See the module docstring."""
    tenant_id = None
    if request.role is not Role.OPERATOR:
        if request.tenant_id is None or db.get(Tenant, request.tenant_id) is None:
            raise _error(422, "tenant_required")
        tenant_id = request.tenant_id
    token, expires_at = issue_admin_token(
        role=request.role,
        tenant_id=tenant_id,
        signing_key=get_settings().session_signing_key,
        ttl=_ADMIN_SESSION_TTL,
    )
    return AdminLoginResponse(
        token=token,
        role=request.role,
        tenant_id=tenant_id,
        expires_at=expires_at,
        permissions=sorted(ROLE_PERMISSIONS[request.role]),
    )


class TenantSummary(BaseModel):
    id: uuid.UUID
    name: str
    api_key: str  # public: it ships in the widget's script URL


@router.get("/tenants", response_model=list[TenantSummary])
def list_tenants(
    session: Annotated[AdminSession, Depends(require_permission(Permission.TENANTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> list[Tenant]:
    """The tenants this session may choose from: all for the operator, its own for the rest."""
    query = select(Tenant).order_by(Tenant.name)
    if session.role not in CROSS_TENANT_ROLES:
        query = query.where(Tenant.id == session.tenant_id)
    return list(db.scalars(query))


class TenantConfigView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    allowed_origins: list[str]
    scope_overrides: dict[str, list[str]] | None


class TenantConfigUpdate(BaseModel):
    """What may be changed. A field left out is left alone; `scope_overrides: null` clears them."""

    model_config = ConfigDict(extra="forbid")

    allowed_origins: list[str] | None = None
    scope_overrides: dict[str, list[str]] | None = None

    @field_validator("allowed_origins")
    @classmethod
    def _plain_origins(cls, origins: list[str] | None) -> list[str] | None:
        for origin in origins or []:
            if normalize_origin(origin) is None:
                raise ValueError(f"not a plain origin (scheme://host[:port]): {origin!r}")
        return origins

    @field_validator("scope_overrides")
    @classmethod
    def _known_scopes(cls, overrides: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
        if overrides and (problems := scope_override_problems(overrides)):
            raise ValueError("; ".join(problems))
        return overrides


def _tenant_or_404(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise _error(404, "tenant_not_found")
    return tenant


@router.get("/tenants/{tenant_id}/config", response_model=TenantConfigView)
def read_config(
    tenant_id: uuid.UUID,
    _: Annotated[AdminSession, Depends(require_tenant_permission(Permission.CONFIG_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> Tenant:
    return _tenant_or_404(db, tenant_id)


@router.patch("/tenants/{tenant_id}/config", response_model=TenantConfigView)
def update_config(
    tenant_id: uuid.UUID,
    update: TenantConfigUpdate,
    _: Annotated[AdminSession, Depends(require_tenant_permission(Permission.CONFIG_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> Tenant:
    tenant = _tenant_or_404(db, tenant_id)
    if "allowed_origins" in update.model_fields_set and update.allowed_origins is not None:
        tenant.allowed_origins = update.allowed_origins
    if "scope_overrides" in update.model_fields_set:
        tenant.scope_overrides = update.scope_overrides or None
    db.commit()
    # The writer sees its own change at once; other instances within the TTL (ADR-0016).
    tenant_configs.invalidate()
    return tenant
