import threading
import time
import uuid

import pytest

from app.core.tenant_config import TenantConfig, TenantConfigCache, TenantConfigUnavailable


def _config(name="Shop", origins=("https://a.example",), overrides=None) -> TenantConfig:
    return TenantConfig(
        tenant_id=uuid.uuid4(),
        name=name,
        api_key=f"pk_{uuid.uuid4().hex[:8]}",
        scope_overrides=overrides,
        allowed_origins=tuple(origins),
    )


class Source:
    def __init__(self, *configs):
        self.configs = list(configs)
        self.calls = 0
        self.broken = False
        self.delay = 0.0
        self.on_call = None

    def __call__(self):
        self.calls += 1
        if self.on_call:
            self.on_call(self.calls)
        time.sleep(self.delay)
        if self.broken:
            raise RuntimeError("db down")
        return list(self.configs)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _cache(source, clock):
    return TenantConfigCache(
        source, ttl_seconds=60, miss_refresh_seconds=5, retry_seconds=5, clock=clock
    )


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
    assert cache.get(a.tenant_id).allowed_origins == ("https://a.example",)

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

    assert cache.get_by_api_key(new.api_key) is None
    assert source.calls == 1
    clock.now += 6
    assert cache.get_by_api_key(new.api_key) == new
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


def test_a_database_failure_keeps_serving_what_it_knows_but_cannot_confirm_a_miss():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    source.broken = True
    clock.now += 61

    assert cache.get(a.tenant_id) == a
    assert cache.all_origins() == frozenset({"https://a.example"})
    with pytest.raises(TenantConfigUnavailable):
        cache.get_by_api_key("pk_never_seen")
    with pytest.raises(TenantConfigUnavailable):
        cache.get(uuid.uuid4())


def test_a_failed_first_load_cannot_answer_and_is_retried_soon_not_after_a_whole_ttl():
    a = _config()
    source, clock = Source(a), Clock()
    source.broken = True
    cache = _cache(source, clock)
    with pytest.raises(TenantConfigUnavailable):
        cache.get(a.tenant_id)
    assert cache.all_origins() == frozenset()

    source.broken = False
    clock.now += 6
    assert cache.get(a.tenant_id) == a


def test_a_failing_database_is_queried_once_per_retry_period_not_once_per_request():
    source, clock = Source(_config()), Clock()
    source.broken = True
    cache = _cache(source, clock)

    for _ in range(40):
        with pytest.raises(TenantConfigUnavailable):
            cache.get_by_api_key("pk_x")
        cache.all_origins()
    assert source.calls == 1

    clock.now += 6
    for _ in range(40):
        with pytest.raises(TenantConfigUnavailable):
            cache.get(uuid.uuid4())
    assert source.calls == 2


def test_a_warm_cache_with_an_old_snapshot_and_a_failing_database_does_not_hammer_it_either():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    source.broken = True
    clock.now += 61

    for _ in range(40):
        cache.get(a.tenant_id)
        with pytest.raises(TenantConfigUnavailable):
            cache.get_by_api_key("pk_unknown")

    assert source.calls == 2


def test_an_invalidation_while_the_database_is_down_does_not_cause_a_query_per_request():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    source.broken = True
    cache.invalidate()

    for _ in range(40):
        cache.get(a.tenant_id)

    assert source.calls == 2


def test_an_invalidation_that_arrives_while_a_reload_is_running_is_not_lost():
    a = _config(origins=("https://a.example",))
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    clock.now += 61
    source.on_call = lambda n: cache.invalidate() if n == 2 else None
    cache.get(a.tenant_id)
    changed = TenantConfig(a.tenant_id, a.name, a.api_key, None, ("https://b.example",))
    source.configs = [changed]

    assert cache.get(a.tenant_id).allowed_origins == ("https://b.example",)


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

    assert source.calls == 2


@pytest.mark.parametrize("state", ["cold", "invalidated"])
def test_many_threads_on_a_cold_or_invalidated_cache_cause_one_load(state):
    a = _config()
    source, clock = Source(a), Clock()
    source.delay = 0.05
    cache = _cache(source, clock)
    if state == "invalidated":
        cache.get(a.tenant_id)
        cache.invalidate()
    base = source.calls
    barrier = threading.Barrier(8)

    def lookup():
        barrier.wait()
        cache.get(a.tenant_id)

    threads = [threading.Thread(target=lookup) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert source.calls == base + 1


def test_the_cors_lookup_never_waits_for_a_reload_in_progress():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)
    clock.now += 61
    source.delay = 0.3

    worker = threading.Thread(target=lambda: cache.get(a.tenant_id))
    worker.start()
    time.sleep(0.05)
    begun = time.perf_counter()
    origins = cache.all_origins()
    waited = time.perf_counter() - begun
    worker.join()

    assert origins == frozenset({"https://a.example"}) and waited < 0.15


def test_clear_forgets_everything_for_tests():
    a = _config()
    source, clock = Source(a), Clock()
    cache = _cache(source, clock)
    cache.get(a.tenant_id)

    cache.clear()
    cache.get(a.tenant_id)

    assert source.calls == 2
