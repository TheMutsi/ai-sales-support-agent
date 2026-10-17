"""`POST /api/auth/login` against a real Postgres: a shop's signed token in,
our session out. The tenant is resolved from the public API key first, so a
token can only be checked against its own tenant's secrets."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.credentials import generate_api_key, generate_secret
from app.core.config import get_settings
from app.db.models import Customer, Tenant, TenantSecret
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


@pytest.fixture
def shop(tenant_wipe):
    """A tenant with one active secret and one customer ('cust-42')."""
    with SessionLocal() as db:
        tenant = Tenant(name="Test shop", api_key=generate_api_key())
        secret = generate_secret()
        db.add(tenant)
        db.flush()
        db.add(TenantSecret(tenant_id=tenant.id, kid="k1", secret=secret))
        customer = Customer(
            name="Ana",
            email="ana@shop.test",
            tenant_id=tenant.id,
            external_id="cust-42",
        )
        db.add(customer)
        db.commit()
        yield {
            "tenant": tenant,
            "customer": customer,
            "secret": secret,
            "api_key": tenant.api_key,
        }


def _store_token(secret: str, sub: str = "cust-42", **claims) -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "exp": now + 300, **claims}, secret, algorithm="HS256")


def _login(api_key: str, token: str):
    return client.post("/api/auth/login", json={"api_key": api_key, "token": token})


def test_valid_token_returns_a_session_for_that_customer(shop):
    response = _login(shop["api_key"], _store_token(shop["secret"]))

    assert response.status_code == 200
    body = response.json()
    assert body["identity_level"] == "store_login"
    assert "customer:read" in body["scopes"]
    claims = jwt.decode(
        body["session_token"], get_settings().session_signing_key, algorithms=["HS256"]
    )
    assert claims["cid"] == str(shop["customer"].id)
    assert claims["tid"] == str(shop["tenant"].id)


def test_unknown_api_key_looks_the_same_as_a_bad_token(shop):
    response = _login("pk_does_not_exist", _store_token(shop["secret"]))

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_token"


def test_token_signed_with_the_wrong_secret_is_rejected(shop):
    response = _login(shop["api_key"], _store_token(generate_secret()))

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_token"


def test_expired_token_is_distinguishable_so_the_widget_can_ask_for_a_new_one(shop):
    response = _login(shop["api_key"], _store_token(shop["secret"], exp=int(time.time()) - 120))

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "token_expired"


def test_subject_with_no_matching_customer_is_rejected(shop):
    response = _login(shop["api_key"], _store_token(shop["secret"], sub="nobody"))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "customer_not_found"


def test_a_customer_of_another_tenant_cannot_be_reached(shop):
    """Same external id under a different tenant must not resolve."""
    with SessionLocal() as db:
        other = Tenant(name="Other shop", api_key=generate_api_key())
        other_secret = generate_secret()
        db.add(other)
        db.flush()
        db.add(TenantSecret(tenant_id=other.id, kid="k1", secret=other_secret))
        db.commit()
        other_key = other.api_key

    response = _login(other_key, _store_token(other_secret, sub="cust-42"))

    assert response.status_code == 403


def test_revoked_secret_no_longer_verifies(shop):
    with SessionLocal() as db:
        db.query(TenantSecret).filter_by(tenant_id=shop["tenant"].id).update({"active": False})
        db.commit()

    response = _login(shop["api_key"], _store_token(shop["secret"]))

    assert response.status_code == 401


def test_tenant_scope_overrides_are_applied_to_the_session(shop):
    with SessionLocal() as db:
        db.query(Tenant).filter_by(id=shop["tenant"].id).update(
            {"scope_overrides": {"store_login": ["kb:read"]}}
        )
        db.commit()

    response = _login(shop["api_key"], _store_token(shop["secret"]))

    assert response.json()["scopes"] == ["kb:read"]
