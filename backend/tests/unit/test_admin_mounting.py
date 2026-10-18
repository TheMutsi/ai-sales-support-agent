"""The placeholder login lets anyone ask for any role, so the admin API must not exist unless
someone switched it on in a local environment: not by default, and not by forgetting APP_ENV."""

import pytest

from app.core.config import Settings


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
