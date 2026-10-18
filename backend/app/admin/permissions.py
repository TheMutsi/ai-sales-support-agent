"""What a person in the back office may do.

Permissions are checked per action: every admin endpoint declares the one it needs (see
`app.api.admin.require_permission`), the way the chat declares the scope each intent needs
(ADR-0014). Roles are only bundles of permissions, so changing who may do what is a change to
`ROLE_PERMISSIONS`, not to the endpoints. The authorization exists before the authentication
that will feed it (ADR-0016).
"""

from enum import StrEnum


class Permission(StrEnum):
    TENANTS_READ = "tenants:read"
    TENANTS_CREATE = "tenants:create"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    CONVERSATIONS_READ = "conversations:read"
    ESCALATIONS_READ = "escalations:read"
    ESCALATIONS_REPLY = "escalations:reply"


class Role(StrEnum):
    VIEWER = "viewer"
    AGENT = "agent"
    ADMIN = "admin"
    OPERATOR = "operator"


_VIEWER = frozenset(
    {
        Permission.TENANTS_READ,
        Permission.CONFIG_READ,
        Permission.CONVERSATIONS_READ,
        Permission.ESCALATIONS_READ,
    }
)
_AGENT = _VIEWER | {Permission.ESCALATIONS_REPLY}
_ADMIN = _AGENT | {Permission.CONFIG_WRITE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.AGENT: _AGENT,
    Role.ADMIN: _ADMIN,
    Role.OPERATOR: _ADMIN | {Permission.TENANTS_CREATE},
}

# Only the operator works across tenants; every other role is bound to the one it logged in to,
# so one shop's staff never see another shop's data.
CROSS_TENANT_ROLES = frozenset({Role.OPERATOR})


def can_access_tenant(role: Role, bound_tenant: object | None, tenant: object) -> bool:
    return role in CROSS_TENANT_ROLES or (bound_tenant is not None and bound_tenant == tenant)
