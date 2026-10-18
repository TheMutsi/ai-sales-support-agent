"""Each shop lists the origins its widget runs on. CORS headers are decided before the
tenant is known (a preflight carries neither key nor token), so an origin any tenant lists
gets them; the real request is then checked against its own tenant's list."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.conversations import resolve_for_login
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.core.config import get_settings
from app.core.tenant_config import tenant_configs
from app.db.models import Customer, Tenant
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
SHOP_A = "https://shop-a.example"
SHOP_B = "https://shop-b.example"
FIRST_PARTY = "http://localhost:5173"  # the app's own frontend, from CORS_ALLOW_ORIGINS


def _tenant(db, origins):
    tenant = Tenant(name="Shop", api_key=generate_api_key(), allowed_origins=origins)
    db.add(tenant)
    db.flush()
    return tenant


@pytest.fixture
def shops(tenant_wipe):
    with SessionLocal() as db:
        a, b = _tenant(db, [SHOP_A]), _tenant(db, [SHOP_B])
        customer = Customer(name="Ana", email="ana@a.test", tenant_id=a.id)
        db.add(customer)
        db.commit()
        conversation = resolve_for_login(
            db,
            tenant_id=a.id,
            customer_id=customer.id,
            level=IdentityLevel.STORE_LOGIN,
            conversation_id=None,
            now=datetime.now(UTC),
        )
        yield {"a": a, "b": b, "customer": customer, "conversation": conversation}


def _preflight(origin):
    return client.options(
        "/api/conversations",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def _start(api_key, origin=None):
    headers = {"Origin": origin} if origin else {}
    return client.post("/api/conversations", json={"api_key": api_key}, headers=headers)


def test_a_preflight_from_any_tenants_origin_is_accepted(shops):
    for origin in (SHOP_A, SHOP_B):
        assert _preflight(origin).headers["access-control-allow-origin"] == origin


def test_a_preflight_from_an_origin_nobody_listed_is_refused(shops):
    assert "access-control-allow-origin" not in _preflight("https://evil.example").headers


def test_the_apps_own_origin_still_works_without_any_tenant(tenant_wipe):
    assert _preflight(FIRST_PARTY).headers["access-control-allow-origin"] == FIRST_PARTY


def test_a_tenants_own_origin_may_use_its_key(shops):
    assert _start(shops["a"].api_key, SHOP_A).status_code == 200


def test_another_tenants_origin_may_not_use_this_key(shops):
    """Shop B's page must not be able to start conversations on shop A's key."""
    response = _start(shops["a"].api_key, SHOP_B)

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "origin_not_allowed"}


def test_a_request_without_an_origin_is_not_a_browser_cross_origin_call(shops):
    assert _start(shops["a"].api_key).status_code == 200


def test_the_apps_own_frontend_may_use_any_key(shops):
    assert _start(shops["a"].api_key, FIRST_PARTY).status_code == 200


def test_an_unknown_key_is_still_the_usual_401_whatever_the_origin(shops):
    assert _start("pk_unknown", "https://evil.example").status_code == 401


def _session_headers(shops, origin=None):
    token, _ = issue_session_token(
        tenant_id=shops["a"].id,
        conversation_id=shops["conversation"].id,
        customer_id=shops["customer"].id,
        level=IdentityLevel.STORE_LOGIN,
        signing_key=get_settings().session_signing_key,
        ttl=timedelta(hours=1),
    )
    headers = {"Authorization": f"Bearer {token}"}
    return {**headers, "Origin": origin} if origin else headers


def test_a_session_is_only_usable_from_its_tenants_origins(shops):
    url = f"/api/conversations/{shops['conversation'].id}/messages"

    assert client.get(url, headers=_session_headers(shops, SHOP_A)).status_code == 200
    stolen = client.get(url, headers=_session_headers(shops, SHOP_B))
    assert stolen.status_code == 403 and stolen.json()["detail"] == {"code": "origin_not_allowed"}


def test_a_new_origin_is_accepted_once_the_cache_expires_or_is_invalidated(tenant_wipe, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(tenant_configs, "_clock", lambda: now[0])
    assert "access-control-allow-origin" not in _preflight(SHOP_A).headers

    with SessionLocal() as db:
        _tenant(db, [SHOP_A])
        db.commit()
    assert "access-control-allow-origin" not in _preflight(SHOP_A).headers  # still cached
    now[0] += get_settings().tenant_config_ttl_seconds + 1

    assert _preflight(SHOP_A).headers["access-control-allow-origin"] == SHOP_A


def test_an_origin_change_applies_at_once_when_the_cache_is_invalidated(tenant_wipe):
    with SessionLocal() as db:
        tenant = _tenant(db, [SHOP_A])
        db.commit()
        tenant_id = tenant.id
    assert _preflight(SHOP_A).headers["access-control-allow-origin"] == SHOP_A

    with SessionLocal() as db:
        db.get(Tenant, tenant_id).allowed_origins = [SHOP_B]
        db.commit()
    assert _preflight(SHOP_A).headers.get("access-control-allow-origin") == SHOP_A  # cached
    tenant_configs.invalidate()

    assert "access-control-allow-origin" not in _preflight(SHOP_A).headers
    assert _preflight(SHOP_B).headers["access-control-allow-origin"] == SHOP_B


def test_a_tenant_created_a_moment_ago_is_not_treated_as_unknown(tenant_wipe, monkeypatch):
    """An unknown tenant skips the origin check, so a stale snapshot must not make a real one look
    unknown: a miss reloads (throttled), and the new tenant's origin check applies."""
    now = [1000.0]
    monkeypatch.setattr(tenant_configs, "_clock", lambda: now[0])
    client.get("/api/health")
    assert tenant_configs.all_origins() == frozenset()  # snapshot loaded, no tenants yet
    with SessionLocal() as db:
        tenant = _tenant(db, [SHOP_A])
        db.commit()
        api_key = tenant.api_key

    now[0] += 6  # past the throttle for reloading on a miss
    response = client.post(
        "/api/conversations", json={"api_key": api_key}, headers={"Origin": SHOP_B}
    )

    assert response.status_code == 403  # the new tenant's origin list was applied, not skipped


def test_a_database_failure_leaves_the_apps_own_origins_working(shops, monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(tenant_configs, "_loader", broken)

    assert "access-control-allow-origin" not in _preflight(SHOP_A).headers
    assert _preflight(FIRST_PARTY).headers["access-control-allow-origin"] == FIRST_PARTY


@pytest.mark.parametrize("bad", ["*", "https://shop.example/path", "null", "shop.example"])
def test_a_tenant_cannot_be_given_a_wildcard_or_a_sloppy_origin(tenant_wipe, bad):
    with pytest.raises(ValueError):
        Tenant(name="Shop", api_key=generate_api_key(), allowed_origins=[bad])


def test_origins_are_stored_normalized(tenant_wipe):
    tenant = Tenant(
        name="Shop", api_key=generate_api_key(), allowed_origins=["HTTPS://Shop.Example:443/"]
    )

    assert tenant.allowed_origins == ["https://shop.example"]


# --- when the configuration cannot be read ---------------------------------------------------------


@pytest.fixture
def config_unavailable(monkeypatch):
    def broken():
        raise RuntimeError("db down")

    tenant_configs.clear()
    monkeypatch.setattr(tenant_configs, "_loader", broken)


def test_the_origin_check_fails_closed_when_the_tenant_cannot_be_looked_up(config_unavailable):
    """An unknown tenant skips the origin check, so "I cannot tell" must not look like "unknown"."""
    response = client.post(
        "/api/conversations", json={"api_key": "pk_any"}, headers={"Origin": SHOP_A}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "configuration_unavailable"}}


def test_a_request_with_no_origin_does_not_need_the_configuration_to_pass_the_guard(
    config_unavailable,
):
    """No `Origin` means no browser cross-origin call, which the guard never checked: it must not
    start failing just because the cache cannot answer."""
    response = client.post("/api/conversations", json={"api_key": "pk_any"})

    assert response.status_code != 503


def test_a_chat_turn_fails_closed_and_leaves_no_turn_open_when_the_scopes_cannot_be_read(
    shops, config_unavailable
):
    """The scope overrides can restrict what a visitor may do: ignoring them would widen it. And
    the failure must come before the turn is opened, or the conversation stays locked."""
    from app.db.models import Conversation

    headers = _session_headers(shops, None)
    body = {"message": "hello", "message_id": str(uuid.uuid4())}

    response = client.post("/api/chat", json=body, headers=headers)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "configuration_unavailable"}}
    with SessionLocal() as db:
        assert db.get(Conversation, shops["conversation"].id).turn_id is None

