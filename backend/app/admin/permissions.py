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

CROSS_TENANT_ROLES = frozenset({Role.OPERATOR})


def can_access_tenant(role: Role, bound_tenant: object | None, tenant: object) -> bool:
    return role in CROSS_TENANT_ROLES or (bound_tenant is not None and bound_tenant == tenant)
