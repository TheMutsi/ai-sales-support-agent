"""The chat reads the tenant's scope overrides from the configuration cache, not the database."""

import uuid

from app.core.tenant_config import TenantConfig, TenantConfigCache


class _Source:
    def __init__(self, *configs):
        self.configs, self.calls = list(configs), 0

    def __call__(self):
        self.calls += 1
        return list(self.configs)


def test_the_chat_reads_scope_overrides_from_the_cache_not_the_database(monkeypatch):
    from app.api import chat as chat_module
    from app.auth.scopes import IdentityLevel
    from app.auth.session import SessionClaims

    tenant = TenantConfig(uuid.uuid4(), "Shop", "pk_x", {"order_lookup": ["kb:read"]}, ())
    cache = TenantConfigCache(_Source(tenant), ttl_seconds=60)
    monkeypatch.setattr(chat_module, "tenant_configs", cache)
    session = SessionClaims(
        tenant_id=tenant.tenant_id,
        conversation_id=uuid.uuid4(),
        customer_id=None,
        level=IdentityLevel.ANONYMOUS,
    )

    assert chat_module._scope_overrides(session) == {"order_lookup": ["kb:read"]}
    assert chat_module._scope_overrides(session) == {"order_lookup": ["kb:read"]}
    assert cache._loader.calls == 1  # two turns, one read of the configuration
    unknown = SessionClaims(
        tenant_id=uuid.uuid4(), conversation_id=uuid.uuid4(), customer_id=None,
        level=IdentityLevel.ANONYMOUS,
    )
    assert chat_module._scope_overrides(unknown) is None


