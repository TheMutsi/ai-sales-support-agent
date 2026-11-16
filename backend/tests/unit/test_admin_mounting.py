import pytest

from app.core.config import Settings, get_settings


def _settings(**values) -> Settings:
    return Settings(_env_file=None, session_signing_key="k" * 40, audit_hmac_key="a" * 40, secrets_encryption_key="u8LHfPlALFyX_gGFRXbIv-3Er6qUqIN8um7hlZVvkag=", **values)


@pytest.mark.parametrize(
    ("values", "mounted"),
    [
        ({}, False),
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
    from fastapi.testclient import TestClient

    from app.main import app

    assert not any(getattr(r, "path", "").startswith("/api/admin") for r in app.routes)
    assert TestClient(app).post("/api/admin/session", json={"role": "operator"}).status_code == 404
