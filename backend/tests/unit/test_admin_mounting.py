"""The placeholder login lets anyone ask for any role, so the admin API must not exist unless
someone switched it on in a local environment: not by default, and not by forgetting APP_ENV."""

import pytest

from app.core.config import Settings, get_settings


def _settings(**values) -> Settings:
    return Settings(_env_file=None, session_signing_key="k" * 40, audit_hmac_key="a" * 40, **values)


@pytest.mark.parametrize(
    ("values", "mounted"),
    [
        ({}, False),  # the default environment is "development": that alone must not mount it
        ({"admin_api_enabled": True}, True),
        ({"admin_api_enabled": True, "app_env": "local"}, True),
        ({"admin_api_enabled": True, "app_env": "production"}, False),
        ({"admin_api_enabled": True, "app_env": "staging"}, False),
        ({"admin_api_enabled": False, "app_env": "local"}, False),
    ],
)
def test_when_the_admin_api_is_mounted(values, mounted):
    assert _settings(**values).admin_api_is_mounted is mounted


@pytest.mark.skipif(
    get_settings().admin_api_enabled, reason="this machine switched the admin API on in its .env"
)
def test_the_default_app_has_no_admin_routes():
    """The `if` in `main.py`, not only the property it reads: without ADMIN_API_ENABLED the app
    that is deployed answers 404 for the login."""
    from fastapi.testclient import TestClient

    from app.main import app

    assert not any(getattr(r, "path", "").startswith("/api/admin") for r in app.routes)
    assert TestClient(app).post("/api/admin/session", json={"role": "operator"}).status_code == 404
