import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select

from app.business.escalation import SupportHours
from app.core.config import get_settings
from app.db.models import Tenant
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantConfig:
    tenant_id: uuid.UUID
    name: str
    api_key: str
    scope_overrides: dict | None
    allowed_origins: tuple[str, ...]
    support_hours: SupportHours | None = None


@dataclass(frozen=True)
class _Snapshot:
    by_id: dict[uuid.UUID, TenantConfig]
    by_api_key: dict[str, TenantConfig]
    origins: frozenset[str]
    loaded_at: float
    generation: int


def _support_hours_of(tenant: Tenant) -> SupportHours | None:
    try:
        return SupportHours.from_config(tenant.support_hours)
    except (KeyError, ValueError, TypeError):
        logger.exception("ignoring the invalid support_hours of tenant %s", tenant.id)
        return None


def load_all_tenant_configs() -> list[TenantConfig]:
    with SessionLocal() as db:
        rows = db.execute(select(Tenant)).scalars().all()
        return [
            TenantConfig(
                tenant_id=t.id,
                name=t.name,
                api_key=t.api_key,
                scope_overrides=t.scope_overrides,
                allowed_origins=tuple(t.allowed_origins or ()),
                support_hours=_support_hours_of(t),
            )
            for t in rows
        ]


class TenantConfigUnavailable(Exception):
    pass


class TenantConfigCache:
    def __init__(
        self,
        loader: Callable[[], list[TenantConfig]] = load_all_tenant_configs,
        *,
        ttl_seconds: float = 60.0,
        miss_refresh_seconds: float = 5.0,
        retry_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._ttl = ttl_seconds
        self._miss_refresh = miss_refresh_seconds
        self._retry = retry_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot: _Snapshot | None = None
        self._generation = 0
        self._last_attempt = float("-inf")
        self._failed_at: float | None = None

    def _out_of_date(self) -> bool:
        snapshot = self._snapshot
        return (
            snapshot is None
            or snapshot.generation != self._generation
            or self._clock() - snapshot.loaded_at > self._ttl
        )

    def _attempt(self, still_needed: Callable[[], bool], *, blocking: bool = True) -> None:
        if not self._lock.acquire(blocking=blocking):
            return
        try:
            if not still_needed():
                return
            now = self._clock()
            if self._failed_at is not None and now - self._failed_at < self._retry:
                return
            self._last_attempt = now
            generation = self._generation
            try:
                configs = self._loader()
            except Exception:
                logger.exception("could not load the tenants' configuration")
                self._failed_at = now
                return
            self._failed_at = None
            self._snapshot = _Snapshot(
                by_id={c.tenant_id: c for c in configs},
                by_api_key={c.api_key: c for c in configs},
                origins=frozenset(o for c in configs for o in c.allowed_origins),
                loaded_at=now,
                generation=generation,
            )
        finally:
            self._lock.release()

    def _current(self, *, blocking: bool = True) -> _Snapshot:
        if self._out_of_date():
            self._attempt(self._out_of_date, blocking=blocking)
        snapshot = self._snapshot
        if snapshot is None:
            raise TenantConfigUnavailable("the tenants' configuration has not been loaded")
        return snapshot

    def _confirm_a_miss(self) -> _Snapshot:
        def may_exist_now() -> bool:
            return self._failed_at is not None or self._clock() - self._last_attempt > self._miss_refresh

        if may_exist_now():
            self._attempt(may_exist_now)
        if self._failed_at is not None:
            raise TenantConfigUnavailable("cannot confirm that this tenant does not exist")
        return self._snapshot  # type: ignore[return-value]

    def get(self, tenant_id: uuid.UUID) -> TenantConfig | None:
        config = self._current().by_id.get(tenant_id)
        return config if config is not None else self._confirm_a_miss().by_id.get(tenant_id)

    def get_by_api_key(self, api_key: str) -> TenantConfig | None:
        config = self._current().by_api_key.get(api_key)
        return config if config is not None else self._confirm_a_miss().by_api_key.get(api_key)

    def all_origins(self) -> frozenset[str]:
        try:
            return self._current(blocking=False).origins
        except TenantConfigUnavailable:
            return frozenset()

    def invalidate(self) -> None:
        self._generation += 1

    def clear(self) -> None:
        with self._lock:
            self._snapshot, self._failed_at = None, None
            self._last_attempt = float("-inf")


tenant_configs = TenantConfigCache(ttl_seconds=get_settings().tenant_config_ttl_seconds)
