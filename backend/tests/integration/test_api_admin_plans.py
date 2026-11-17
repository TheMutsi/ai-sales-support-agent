import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import ADMIN_ROUTERS
from app.auth.credentials import generate_api_key
from app.db.models import Plan, Tenant
from app.db.session import SessionLocal

app = FastAPI()
for router in ADMIN_ROUTERS:
    app.include_router(router, prefix="/api")
client = TestClient(app)

PLAN_SLUGS = ["zz-test-big", "zz-test-small"]


@pytest.fixture
def tenants(tenant_wipe):
    with SessionLocal() as db:
        a, b = Tenant(name="Shop A", api_key=generate_api_key()), Tenant(name="Shop B", api_key=generate_api_key())
        db.add_all(
            [
                a,
                b,
                Plan(slug="zz-test-big", name="Big", price_cents=99900, billing_period="monthly"),
                Plan(slug="zz-test-small", name="Small", price_cents=100, billing_period="monthly"),
            ]
        )
        db.commit()
        yield {"a": a.id, "b": b.id}
    with SessionLocal() as db:
        db.query(Plan).filter(Plan.slug.in_(PLAN_SLUGS)).delete()
        db.commit()


def _login(role, tenant_id=None):
    body = client.post(
        "/api/admin/session", json={"role": role, "tenant_id": str(tenant_id) if tenant_id else None, "name": "Lucia"}
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_plans_come_back_with_slug_and_name_cheapest_first(tenants):
    response = client.get(f"/api/admin/tenants/{tenants['a']}/plans", headers=_login("admin", tenants["a"]))
    assert response.status_code == 200
    ours = [plan for plan in response.json() if plan["slug"] in PLAN_SLUGS]
    assert ours == [{"slug": "zz-test-small", "name": "Small"}, {"slug": "zz-test-big", "name": "Big"}]


def test_a_viewer_can_read_the_plans(tenants):
    response = client.get(f"/api/admin/tenants/{tenants['a']}/plans", headers=_login("viewer", tenants["a"]))
    assert response.status_code == 200


def test_another_tenant_and_a_missing_session_are_refused(tenants):
    url = f"/api/admin/tenants/{tenants['a']}/plans"
    assert client.get(url, headers=_login("admin", tenants["b"])).status_code == 403
    assert client.get(url).status_code == 401
