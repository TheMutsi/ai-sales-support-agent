"""The configuration of every tenant, cached: read on every request, changed rarely.

One snapshot of all tenants (their origins, scope overrides and API key) serves the lookups by id
and by API key and the union of origins the CORS layer needs, so a request costs a dictionary
lookup instead of a query. The snapshot is reloaded:

- when it is older than the TTL, so a change made anywhere reaches every instance within a bounded
  time (the cache is in-process: with several API instances a change shows up on the others after
  the TTL, not at once);
- when asked to (`invalidate`), which the back office does after it writes, so the instance that
  wrote sees its own change at once, even if the invalidation lands while a reload is running;
- when something is not found, but at most once every few seconds: a tenant created a moment ago
  must not be mistaken for an unknown one, and someone guessing API keys must not turn every guess
  into a query.

**When the database cannot be read** the previous snapshot keeps serving what it knows, and the
database is tried again after a short pause, not on every request. But a lookup that finds nothing
cannot then be called "unknown": an unknown tenant skips the origin check, so mistaking a real one
for it would open that check. It raises `TenantConfigUnavailable` instead, and the caller fails
closed. Only `all_origins`, for the CORS layer, never raises and never waits for a reload (it runs
on the event loop): it serves the current snapshot, or nothing.

Reloads are single-flight: threads that find the snapshot out of date at the same moment cause one
query. Callers must treat what they get as read-only.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select

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


@dataclass(frozen=True)
class _Snapshot:
    by_id: dict[uuid.UUID, TenantConfig]
    by_api_key: dict[str, TenantConfig]
    origins: frozenset[str]
    loaded_at: float
    generation: int


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
            )
            for t in rows
        ]


class TenantConfigUnavailable(Exception):
    """The configuration could not be read, and what was asked cannot be answered from what is
    cached (never loaded, or a lookup that found nothing and could not be confirmed)."""


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
        self._generation = 0  # bumped by invalidate(); a snapshot older than it is out of date
        self._last_attempt = float("-inf")
        self._failed_at: float | None = None  # when the last attempt failed, if it did

    def _out_of_date(self) -> bool:
        snapshot = self._snapshot
        return (
            snapshot is None
            or snapshot.generation != self._generation
            or self._clock() - snapshot.loaded_at > self._ttl
        )

    def _attempt(self, still_needed: Callable[[], bool], *, blocking: bool = True) -> None:
        """Tries to load a new snapshot. `still_needed` is asked again once the lock is held: if
        another thread reloaded while this one waited, there is nothing left to do (single-flight:
        threads that find the snapshot out of date together cause one query). A recent failure is
        not retried until the retry pause has passed."""
        if not self._lock.acquire(blocking=blocking):
            return
        try:
            if not still_needed():
                return
            now = self._clock()
            if self._failed_at is not None and now - self._failed_at < self._retry:
                return
            self._last_attempt = now
            # Read before the query: an invalidation that lands while it runs leaves this
            # snapshot already out of date, and the next lookup reloads it.
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
        """A lookup found nothing. Reload, but only if the last attempt is old enough that a new
        tenant may exist; otherwise a burst of unknown keys would be a burst of queries. If the
        database cannot be read, a miss is not an answer."""

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
        """For the CORS layer, which runs on the event loop: never raises, never waits."""
        try:
            return self._current(blocking=False).origins
        except TenantConfigUnavailable:
            return frozenset()

    def invalidate(self) -> None:
        """Reload at the next lookup. The back office calls this after changing a tenant."""
        self._generation += 1

    def clear(self) -> None:
        """Forget everything (tests)."""
        with self._lock:
            self._snapshot, self._failed_at = None, None
            self._last_attempt = float("-inf")


tenant_configs = TenantConfigCache(ttl_seconds=get_settings().tenant_config_ttl_seconds)
