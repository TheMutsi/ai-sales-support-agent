"""Per-tenant allowed origins.

Two parts. `TenantCORSMiddleware` decides the CORS headers, which a browser needs before
it sends the real request. A preflight carries neither the API key nor a token, so the
tenant is not known yet: an origin gets headers if the app lists it or any tenant does. The real
request is then checked against *its own* tenant's list (`check_origin`), so shop B's page cannot
use shop A's key. Both read tenant configuration from `app.core.tenant_config`, a cache.

Only requests that carry an `Origin` header are checked, i.e. a browser calling cross-origin.
Anyone can leave the header off or forge it from a script, so this keeps one shop's page from
using another's key in a visitor's browser; it is not authentication.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from starlette.middleware.cors import CORSMiddleware

from app.api.deps import require_session
from app.auth.session import SessionClaims
from app.core.config import get_settings
from app.core.origins import normalize_origin
from app.core.tenant_config import TenantConfig, tenant_configs


class TenantCORSMiddleware(CORSMiddleware):
    def is_allowed_origin(self, origin: str) -> bool:
        return super().is_allowed_origin(origin) or origin in tenant_configs.all_origins()


def check_origin(request: Request, tenant: TenantConfig | None) -> None:
    """Refuses a browser request whose origin is not one of this tenant's. A request without
    an origin, from the app's own frontend, or for an unknown tenant (which fails on its own)
    passes."""
    origin = request.headers.get("origin")
    if origin is None or tenant is None or origin in get_settings().cors_allow_origins:
        return
    if normalize_origin(origin) not in tenant.allowed_origins:
        raise HTTPException(status_code=403, detail={"code": "origin_not_allowed"})


def check_origin_for_api_key(request: Request, api_key: str) -> None:
    check_origin(request, tenant_configs.get_by_api_key(api_key))


def _check_origin_for_session(
    request: Request, session: Annotated[SessionClaims, Depends(require_session)]
) -> None:
    check_origin(request, tenant_configs.get(session.tenant_id))


origin_guard_for_session = Depends(_check_origin_for_session)
