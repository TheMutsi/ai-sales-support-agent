"""The cache of tenant configuration: read often, changed rarely. One snapshot of every tenant,
reloaded when it is old, when it is asked to, and (throttled) when something is not found, so a
tenant created a moment ago is not mistaken for an unknown one."""

import threading
import time
import uuid

from app.core.tenant_config import TenantConfig, TenantConfigCache


def _config(name="Shop", origins=("https://a.example",), overrides=None) -> TenantConfig:
    return TenantConfig(
        tenant_id=uuid.uuid4(),
        name=name,
        api_key=f"pk_{uuid.uuid4().hex[:8]}",
        scope_overrides=overrides,
        allowed_origins=tuple(origins),
    )


class Source:
    """A loader that records how often it was called and can be changed or broken."""

    def __init__(self, *configs):
        self.configs = list(configs)
        self.calls = 0
        self.broken = False
        self.delay = 0.0

    def __call__(self):
        self.calls += 1
        time.sleep(self.delay)  # a slow query is what makes threads pile up on an old snapshot
        if self.broken:
            raise RuntimeError("db down")
        return list(self.configs)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _cache(source, clock, **kw):
    return TenantConfigCache(source, ttl_seconds=60, miss_refresh_seconds=5, retry_seconds=5, clock=clock, **kw)


def test_it_loads_once_and_serves_every_lookup_from_memory():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)

    for _ in range(5):
        assert cache.get(a.tenant_id) == a
        assert cache.get_by_api_key(a.api_key) == a
        assert cache.all_origins() == frozenset({"https://a.example"})

    assert source.calls == 1


def test_it_reloads_when_the_snapshot_is_older_than_the_ttl():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)

    clock.now += 61
    cache.get(a.tenant_id)

    assert source.calls == 2


def test_a_change_is_seen_after_the_ttl_or_at_once_when_invalidated():
    a = _config(origins=("https://a.example",))
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    assert cache.get(a.tenant_id).allowed_origins == ("https://a.example",)

    changed = TenantConfig(a.tenant_id, a.name, a.api_key, None, ("https://b.example",))
    source.configs = [changed]
    assert cache.get(a.tenant_id).allowed_origins == ("https://a.example",)  # still the old one

    cache.invalidate()
    assert cache.get(a.tenant_id).allowed_origins == ("https://b.example",)
    assert cache.all_origins() == frozenset({"https://b.example"})


def test_a_tenant_created_after_the_load_is_found_by_a_throttled_reload_on_a_miss():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    new = _config(name="New")
    source.configs = [a, new]

    assert cache.get_by_api_key(new.api_key) is None  # too soon: no reload for a miss
    assert source.calls == 1
    clock.now += 6
    assert cache.get_by_api_key(new.api_key) == new  # now it may refresh, and finds it
    assert source.calls == 2


def test_guessing_unknown_keys_cannot_hammer_the_database():
    source, clock = Source(_config()), Clock()
    cache = _cache(source, clock)
    cache.all_origins()

    clock.now += 6
    for _ in range(50):
        assert cache.get_by_api_key("pk_unknown") is None
        assert cache.get(uuid.uuid4()) is None

    assert source.calls == 2, "one reload for the whole burst, not one per guess"


def test_a_database_failure_keeps_the_previous_snapshot_and_never_raises():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    source.broken = True

    clock.now += 61
    assert cache.get(a.tenant_id) == a  # the old snapshot still serves
    assert cache.all_origins() == frozenset({"https://a.example"})


def test_a_failed_first_load_is_retried_soon_not_after_a_whole_ttl():
    a = _config()
    source, clock = Source(a), Clock()
    source.broken = True
    cache = _cache(source, clock)
    assert cache.get(a.tenant_id) is None and cache.all_origins() == frozenset()

    source.broken = False
    clock.now += 6  # retry_seconds, far less than the 60 s TTL
    assert cache.get(a.tenant_id) == a


def test_many_threads_hitting_an_old_snapshot_cause_one_reload():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    clock.now += 61
    source.delay = 0.05
    barrier = threading.Barrier(8)

    def lookup():
        barrier.wait()
        cache.get(a.tenant_id)

    threads = [threading.Thread(target=lookup) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert source.calls == 2  # the first load plus one reload, not one per thread


def test_clear_forgets_everything_for_tests():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)

    cache.clear()
    cache.get(a.tenant_id)

    assert source.calls == 2
