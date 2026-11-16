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
    origin = request.headers.get("origin")
    if origin is None or tenant is None or origin in get_settings().cors_allow_origins:
        return
    if normalize_origin(origin) not in tenant.allowed_origins:
        raise HTTPException(status_code=403, detail={"code": "origin_not_allowed"})


def _needs_a_check(request: Request) -> bool:
    origin = request.headers.get("origin")
    return origin is not None and origin not in get_settings().cors_allow_origins


def check_origin_for_api_key(request: Request, api_key: str) -> None:
    if _needs_a_check(request):
        check_origin(request, tenant_configs.get_by_api_key(api_key))


def _check_origin_for_session(
    request: Request, session: Annotated[SessionClaims, Depends(require_session)]
) -> None:
    if _needs_a_check(request):
        check_origin(request, tenant_configs.get(session.tenant_id))


origin_guard_for_session = Depends(_check_origin_for_session)
