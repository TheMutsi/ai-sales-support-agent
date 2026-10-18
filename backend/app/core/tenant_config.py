"""The configuration of every tenant, cached: read on every request, changed rarely.

One snapshot of all tenants (their origins, scope overrides and API key) serves the lookups by id
and by API key and the union of origins the CORS layer needs, so a request costs a dictionary
lookup instead of a query. The snapshot is reloaded:

- when it is older than the TTL, so a change made anywhere reaches every instance within a bounded
  time (the cache is in-process: with several API instances a change shows up on the others after
  the TTL, not at once);
- when asked to (`invalidate`), which the back office does after it writes, so the instance that
  wrote sees its own change immediately;
- when something is not found, but at most once every few seconds: a tenant created a moment ago
  must not be mistaken for an unknown one (an unknown tenant skips the origin check), and someone
  guessing API keys must not turn every guess into a query.

If the database cannot be read the previous snapshot keeps serving and the failure is logged:
configuration lookups never take the API down. Callers must treat what they get as read-only.
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
        self._stale = False

    def _reload(self, *, if_older_than: float | None) -> _Snapshot:
        """Loads a new snapshot unless another thread just did (`if_older_than` is the snapshot
        age this caller saw: a newer one means somebody else already reloaded)."""
        with self._lock:
            current = self._snapshot
            if current is not None and if_older_than is not None and current.loaded_at > if_older_than:
                return current
            now = self._clock()
            try:
                configs = self._loader()
            except Exception:
                logger.exception("could not load the tenants' configuration")
                # Keep what we have, and retry soon rather than after a whole TTL.
                keep = current or _Snapshot({}, {}, frozenset(), 0.0)
                self._snapshot = _Snapshot(
                    keep.by_id, keep.by_api_key, keep.origins, now - self._ttl + self._retry
                )
                return self._snapshot
            self._stale = False
            self._snapshot = _Snapshot(
                by_id={c.tenant_id: c for c in configs},
                by_api_key={c.api_key: c for c in configs},
                origins=frozenset(o for c in configs for o in c.allowed_origins),
                loaded_at=now,
            )
            return self._snapshot

    def _current(self) -> _Snapshot:
        snapshot = self._snapshot
        if snapshot is None or self._stale or self._clock() - snapshot.loaded_at > self._ttl:
            return self._reload(
                if_older_than=None if snapshot is None or self._stale else snapshot.loaded_at
            )
        return snapshot

    def _on_a_miss(self, snapshot: _Snapshot) -> _Snapshot:
        """A lookup found nothing. Reload, but only if the snapshot is old enough that a new
        tenant may exist; otherwise a burst of unknown keys would be a burst of queries."""
        if self._clock() - snapshot.loaded_at > self._miss_refresh:
            return self._reload(if_older_than=snapshot.loaded_at)
        return snapshot

    def get(self, tenant_id: uuid.UUID) -> TenantConfig | None:
        snapshot = self._current()
        config = snapshot.by_id.get(tenant_id)
        if config is None:
            config = self._on_a_miss(snapshot).by_id.get(tenant_id)
        return config

    def get_by_api_key(self, api_key: str) -> TenantConfig | None:
        snapshot = self._current()
        config = snapshot.by_api_key.get(api_key)
        if config is None:
            config = self._on_a_miss(snapshot).by_api_key.get(api_key)
        return config

    def all_origins(self) -> frozenset[str]:
        return self._current().origins

    def invalidate(self) -> None:
        """Reload at the next lookup. The back office calls this after changing a tenant."""
        self._stale = True

    def clear(self) -> None:
        """Forget everything (tests)."""
        with self._lock:
            self._snapshot, self._stale = None, False


tenant_configs = TenantConfigCache(ttl_seconds=get_settings().tenant_config_ttl_seconds)
