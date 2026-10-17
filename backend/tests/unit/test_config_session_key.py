import pytest
from pydantic import ValidationError

from app.core.config import Settings

REAL_KEY = "a-real-session-signing-key-32-chars!"


@pytest.mark.parametrize("env", ["production", "prod", "staging", "anything-else"])
def test_every_non_local_environment_refuses_the_dev_session_key(env):
    """The dev key is public (it's in the repo), so a deployment that forgot to set
    its own — under whatever name it gave its environment — must fail at startup
    instead of signing sessions anyone can forge."""
    with pytest.raises(ValidationError, match="SESSION_SIGNING_KEY"):
        Settings(app_env=env)


@pytest.mark.parametrize("env", ["development", "local", "test"])
def test_local_environments_may_use_the_default_key(env):
    assert Settings(app_env=env).session_signing_key


def test_a_real_key_is_accepted_anywhere():
    settings = Settings(app_env="production", session_signing_key=REAL_KEY)

    assert settings.session_signing_key == REAL_KEY


@pytest.mark.parametrize("env", ["development", "production"])
def test_a_short_key_is_rejected_in_every_environment(env):
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(app_env=env, session_signing_key="short")
