import uuid

from app.rag import catalog
from app.rag.catalog import DocumentCatalogCache
from app.schemas.rag import DocumentMapEntry


def _entry(title: str, plan_scope: str | None = None) -> DocumentMapEntry:
    return DocumentMapEntry(
        document_id=uuid.uuid4(), title=title, when_to_use="when", estimated_tokens=10, plan_scope=plan_scope
    )


class _Loader:
    def __init__(self, entries):
        self.entries = tuple(entries)
        self.calls: list[uuid.UUID] = []

    def __call__(self, tenant_id):
        self.calls.append(tenant_id)
        return self.entries


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_loads_once_per_tenant_within_the_ttl():
    loader = _Loader([_entry("a")])
    cache = DocumentCatalogCache(loader, ttl_seconds=60, clock=_Clock())
    tenant, other = uuid.uuid4(), uuid.uuid4()

    cache.get(tenant)
    cache.get(tenant)
    cache.get(other)

    assert loader.calls == [tenant, other]


def test_reloads_after_the_ttl():
    clock = _Clock()
    loader = _Loader([_entry("a")])
    cache = DocumentCatalogCache(loader, ttl_seconds=60, clock=clock)
    tenant = uuid.uuid4()

    cache.get(tenant)
    clock.now = 61
    cache.get(tenant)

    assert loader.calls == [tenant, tenant]


def test_invalidate_forces_a_reload_of_that_tenant_only():
    loader = _Loader([_entry("a")])
    cache = DocumentCatalogCache(loader, ttl_seconds=60, clock=_Clock())
    tenant, other = uuid.uuid4(), uuid.uuid4()
    cache.get(tenant)
    cache.get(other)

    cache.invalidate(tenant)
    cache.get(tenant)
    cache.get(other)

    assert loader.calls == [tenant, other, tenant]


def test_clear_forgets_every_tenant():
    loader = _Loader([_entry("a")])
    cache = DocumentCatalogCache(loader, ttl_seconds=60, clock=_Clock())
    tenant = uuid.uuid4()
    cache.get(tenant)

    cache.clear()
    cache.get(tenant)

    assert loader.calls == [tenant, tenant]


def test_the_map_for_a_plan_keeps_its_documents_and_the_unscoped_ones(monkeypatch):
    pro, starter, general = _entry("pro", "pro"), _entry("starter", "starter"), _entry("general")
    cache = DocumentCatalogCache(_Loader([pro, starter, general]), ttl_seconds=60, clock=_Clock())
    monkeypatch.setattr(catalog, "document_catalog", cache)
    tenant = uuid.uuid4()

    assert catalog.get_document_map(tenant, "pro") == (pro, general)
    assert catalog.get_document_map(tenant) == (general,)


def test_module_invalidate_drops_the_cached_map(monkeypatch):
    loader = _Loader([_entry("a")])
    monkeypatch.setattr(catalog, "document_catalog", DocumentCatalogCache(loader, ttl_seconds=60, clock=_Clock()))
    tenant = uuid.uuid4()
    catalog.get_document_map(tenant)

    catalog.invalidate(tenant)
    catalog.get_document_map(tenant)

    assert loader.calls == [tenant, tenant]
