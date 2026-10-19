import pytest
from pydantic import ValidationError

from app.core.config import Settings

REAL_KEY = "a-real-session-signing-key-32-chars!"
AUDIT_KEY = "an-audit-hmac-key-of-32-characters!!"


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
    settings = Settings(app_env="production", session_signing_key=REAL_KEY, audit_hmac_key=AUDIT_KEY, secrets_encryption_key="u8LHfPlALFyX_gGFRXbIv-3Er6qUqIN8um7hlZVvkag=")

    assert settings.session_signing_key == REAL_KEY


@pytest.mark.parametrize("env", ["development", "production"])
def test_a_short_key_is_rejected_in_every_environment(env):
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(app_env=env, session_signing_key="short")


# --- the audit key: the email and order hashes in `identification_events` -------------------


@pytest.mark.parametrize("env", ["production", "prod", "staging"])
def test_a_deployment_must_set_its_own_audit_key(env):
    """Rotating the session key must not change every hash, and a leaked session key must not
    also make the audit hashes guessable: outside local envs the audit key is its own secret."""
    with pytest.raises(ValidationError, match="AUDIT_HMAC_KEY"):
        Settings(app_env=env, session_signing_key=REAL_KEY)


def test_the_audit_key_must_differ_from_the_session_key():
    with pytest.raises(ValidationError, match="differ"):
        Settings(app_env="production", session_signing_key=REAL_KEY, audit_hmac_key=REAL_KEY, secrets_encryption_key="u8LHfPlALFyX_gGFRXbIv-3Er6qUqIN8um7hlZVvkag=")


@pytest.mark.parametrize("env", ["development", "production"])
def test_a_short_audit_key_is_rejected_when_one_is_given(env):
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(app_env=env, session_signing_key=REAL_KEY, audit_hmac_key="short", secrets_encryption_key="u8LHfPlALFyX_gGFRXbIv-3Er6qUqIN8um7hlZVvkag=")


def test_a_real_audit_key_is_used_as_given():
    settings = Settings(app_env="production", session_signing_key=REAL_KEY, audit_hmac_key=AUDIT_KEY, secrets_encryption_key="u8LHfPlALFyX_gGFRXbIv-3Er6qUqIN8um7hlZVvkag=")

    assert settings.audit_key == AUDIT_KEY


@pytest.mark.parametrize("env", ["development", "local", "test"])
def test_local_environments_fall_back_to_the_session_key_for_the_audit_hashes(env):
    settings = Settings(app_env=env)

    assert settings.audit_hmac_key == "" and settings.audit_key == settings.session_signing_key

