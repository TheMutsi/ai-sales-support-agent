"""A forgotten permission check fails here instead of opening a route."""

from fastapi.routing import APIRoute

from app.admin.permissions import Permission
from app.api.admin import ADMIN_ROUTERS

# The routes that cannot ask for a permission: they are how a session is obtained.
OPEN_ROUTES = {("POST", "/admin/session"), ("GET", "/admin/login-options")}


def _routes() -> list[APIRoute]:
    """Every admin route. Anything that is not a plain `APIRoute` (a router nested with
    `include_router` is wrapped) cannot be inspected, and must not be skipped silently."""
    routes = [route for router in ADMIN_ROUTERS for route in router.routes]
    opaque = [route for route in routes if not isinstance(route, APIRoute)]
    assert not opaque, f"cannot read the permissions of {opaque}: mount routers one by one"
    return routes


def _permission_of(route: APIRoute) -> Permission | None:
    return next(
        (
            dep.call.permission
            for dep in route.dependant.dependencies
            if hasattr(dep.call, "permission")
        ),
        None,
    )


def test_every_admin_route_declares_a_permission():
    routes = _routes()
    assert routes
    missing = [
        (method, route.path)
        for route in routes
        for method in route.methods
        if (method, route.path) not in OPEN_ROUTES and _permission_of(route) is None
    ]
    assert missing == []


# Declaring *a* permission is not enough: a PATCH guarded by a read permission would pass that.
EXPECTED = {
    ("GET", "/admin/tenants"): Permission.TENANTS_READ,
    ("GET", "/admin/tenants/{tenant_id}/config"): Permission.CONFIG_READ,
    ("PATCH", "/admin/tenants/{tenant_id}/config"): Permission.CONFIG_WRITE,
    ("GET", "/admin/tenants/{tenant_id}/conversations"): Permission.CONVERSATIONS_READ,
    ("GET", "/admin/tenants/{tenant_id}/conversations/{conversation_id}"): Permission.CONVERSATIONS_READ,
}


def test_each_route_needs_the_right_permission():
    found = {
        (method, route.path): _permission_of(route)
        for route in _routes()
        for method in route.methods
        if (method, route.path) not in OPEN_ROUTES
    }
    assert found == EXPECTED


def test_the_open_routes_are_real_routes():
    paths = {(m, r.path) for r in _routes() for m in r.methods}
    assert OPEN_ROUTES <= paths
