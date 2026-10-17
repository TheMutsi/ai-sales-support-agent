"""Per-tenant allowed origins.

Two parts. `TenantCORSMiddleware` decides the CORS headers, which a browser needs before
it sends the real request. A preflight carries neither the API key nor a token, so the
tenant is not known yet: an origin gets headers if the app lists it or any tenant does
(cached for a minute). The real request is then checked against *its own* tenant's list
(`check_origin`), so shop B's page cannot use shop A's key.

Only requests that carry an `Origin` header are checked, i.e. a browser calling cross-origin.
Anyone can leave the header off or forge it from a script, so this keeps one shop's page from
using another's key in a visitor's browser; it is not authentication.
"""

import logging
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from starlette.middleware.cors import CORSMiddleware

from app.api.deps import require_session
from app.auth.session import SessionClaims
from app.core.config import get_settings
from app.core.origins import normalize_origin
from app.db.models import Tenant
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60


class OriginRegistry:
    """The union of every tenant's origins, reloaded when older than `CACHE_SECONDS`. If the
    database cannot be read, the previous list stays and CORS never takes the API down."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._origins: frozenset[str] = frozenset()
        self._loaded_at: float | None = None

    def _load(self) -> frozenset[str]:
        with SessionLocal() as db:
            lists = db.execute(select(Tenant.allowed_origins)).scalars().all()
        return frozenset(origin for origins in lists for origin in origins or [])

    def is_known(self, origin: str) -> bool:
        now = self._clock()
        if self._loaded_at is None or now - self._loaded_at > CACHE_SECONDS:
            try:
                self._origins = self._load()
            except Exception:
                logger.exception("could not load tenants' allowed origins")
            self._loaded_at = now
        return origin in self._origins

    def clear(self) -> None:
        self._origins, self._loaded_at = frozenset(), None


registry = OriginRegistry()


class TenantCORSMiddleware(CORSMiddleware):
    def is_allowed_origin(self, origin: str) -> bool:
        return super().is_allowed_origin(origin) or registry.is_known(origin)


def check_origin(request: Request, tenant: Tenant | None) -> None:
    """Refuses a browser request whose origin is not one of this tenant's. A request without
    an origin, from the app's own frontend, or for an unknown tenant (which fails on its own)
    passes."""
    origin = request.headers.get("origin")
    if origin is None or tenant is None or origin in get_settings().cors_allow_origins:
        return
    if normalize_origin(origin) not in tenant.allowed_origins:
        raise HTTPException(status_code=403, detail={"code": "origin_not_allowed"})


def check_origin_for_api_key(request: Request, api_key: str) -> None:
    with SessionLocal() as db:
        check_origin(request, db.query(Tenant).filter_by(api_key=api_key).one_or_none())


def _check_origin_for_session(
    request: Request, session: Annotated[SessionClaims, Depends(require_session)]
) -> None:
    with SessionLocal() as db:
        check_origin(request, db.get(Tenant, session.tenant_id))


origin_guard_for_session = Depends(_check_origin_for_session)
