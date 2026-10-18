"""The admin API against a real Postgres: who may see and change what."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import router
from app.auth.credentials import generate_api_key
from app.core.tenant_config import tenant_configs
from app.db.models import Tenant
from app.db.session import SessionLocal

# The router alone: `main` mounts it only when switched on, which a test of the routes must not need.
app = FastAPI()
app.include_router(router, prefix="/api")
client = TestClient(app)


@pytest.fixture
def shops(tenant_wipe):
    with SessionLocal() as db:
        a = Tenant(name="Shop A", api_key=generate_api_key(), allowed_origins=["https://a.example"])
        b = Tenant(name="Shop B", api_key=generate_api_key(), allowed_origins=["https://b.example"])
        db.add_all([a, b])
        db.commit()
        return str(a.id), str(b.id)


def _login(role, tenant_id=None):
    response = client.post("/api/admin/session", json={"role": role, "tenant_id": tenant_id})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_a_request_without_a_session_is_refused(shops):
    a, _ = shops
    assert client.get("/api/admin/tenants").status_code == 401
    assert client.get(f"/api/admin/tenants/{a}/config").status_code == 401


def test_a_non_operator_must_name_an_existing_tenant(shops):
    assert client.post("/api/admin/session", json={"role": "admin"}).status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    response = client.post("/api/admin/session", json={"role": "admin", "tenant_id": missing})
    assert response.status_code == 422


def test_the_session_says_what_the_role_may_do(shops):
    a, _ = shops
    body = client.post("/api/admin/session", json={"role": "viewer", "tenant_id": a}).json()
    assert "config:read" in body["permissions"]
    assert "config:write" not in body["permissions"]


def test_the_operator_sees_every_tenant_and_the_others_only_their_own(shops):
    a, _ = shops
    assert len(client.get("/api/admin/tenants", headers=_login("operator")).json()) == 2
    own = client.get("/api/admin/tenants", headers=_login("admin", a)).json()
    assert [t["id"] for t in own] == [a]


def test_a_tenant_bound_session_cannot_read_another_tenant(shops):
    a, b = shops
    assert client.get(f"/api/admin/tenants/{a}/config", headers=_login("viewer", a)).status_code == 200
    response = client.get(f"/api/admin/tenants/{b}/config", headers=_login("viewer", a))
    assert (response.status_code, response.json()["detail"]["code"]) == (403, "wrong_tenant")
    assert client.get(f"/api/admin/tenants/{b}/config", headers=_login("operator")).status_code == 200


def test_a_viewer_cannot_change_configuration(shops):
    a, _ = shops
    response = client.patch(
        f"/api/admin/tenants/{a}/config",
        json={"allowed_origins": ["https://evil.example"]},
        headers=_login("viewer", a),
    )
    assert (response.status_code, response.json()["detail"]["code"]) == (403, "forbidden")
    with SessionLocal() as db:
        assert db.get(Tenant, a).allowed_origins == ["https://a.example"]


def test_an_admin_changes_origins_and_the_cache_sees_it_at_once(shops):
    a, _ = shops
    assert tenant_configs.get(uuid.UUID(a)).allowed_origins == ("https://a.example",)
    response = client.patch(
        f"/api/admin/tenants/{a}/config",
        json={"allowed_origins": ["https://new.example/", "https://a.example"]},
        headers=_login("admin", a),
    )
    assert response.status_code == 200
    assert response.json()["allowed_origins"] == ["https://new.example", "https://a.example"]
    assert "https://new.example" in tenant_configs.all_origins()


def test_a_removed_origin_stops_being_allowed_at_once(shops):
    a, _ = shops
    assert "https://a.example" in tenant_configs.all_origins()
    client.patch(
        f"/api/admin/tenants/{a}/config",
        json={"allowed_origins": ["https://other.example"]},
        headers=_login("admin", a),
    )
    assert "https://a.example" not in tenant_configs.all_origins()


def test_origins_cannot_be_cleared_with_null(shops):
    a, _ = shops
    response = client.patch(
        f"/api/admin/tenants/{a}/config", json={"allowed_origins": None}, headers=_login("admin", a)
    )
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.get(Tenant, a).allowed_origins == ["https://a.example"]


def test_scope_overrides_are_saved_cleared_and_validated(shops):
    a, _ = shops
    url, headers = f"/api/admin/tenants/{a}/config", _login("admin", a)
    saved = client.patch(url, json={"scope_overrides": {"order_lookup": ["kb:read"]}}, headers=headers)
    assert saved.json()["scope_overrides"] == {"order_lookup": ["kb:read"]}
    # A field left out is left alone.
    kept = client.patch(url, json={"allowed_origins": ["https://a.example"]}, headers=headers)
    assert kept.json()["scope_overrides"] == {"order_lookup": ["kb:read"]}
    cleared = client.patch(url, json={"scope_overrides": None}, headers=headers)
    assert cleared.json()["scope_overrides"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"allowed_origins": ["*"]},
        {"allowed_origins": ["https://a.example/path"]},
        {"scope_overrides": {"nobody": ["kb:read"]}},
        {"scope_overrides": {"store_login": ["kb:write"]}},
        {"scope_overrides": {"order_lookup": ["refund:request"]}},
        {"api_key": "x"},
    ],
)
def test_bad_configuration_is_refused_and_nothing_is_saved(shops, body):
    a, _ = shops
    response = client.patch(f"/api/admin/tenants/{a}/config", json=body, headers=_login("admin", a))
    assert response.status_code == 422
    with SessionLocal() as db:
        tenant = db.get(Tenant, a)
        assert (tenant.allowed_origins, tenant.scope_overrides) == (["https://a.example"], None)
