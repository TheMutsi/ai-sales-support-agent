import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.secrets import SecretUnreadable, decrypt_secret, encrypt_secret


def test_a_secret_round_trips_and_is_not_stored_as_it_was_written():
    stored = encrypt_secret("hunter2")

    assert "hunter2" not in stored
    assert decrypt_secret(stored) == "hunter2"


def test_the_same_secret_encrypts_differently_each_time():
    assert encrypt_secret("hunter2") != encrypt_secret("hunter2")


def test_a_value_made_with_another_key_or_altered_is_unreadable():
    foreign = Fernet(Fernet.generate_key()).encrypt(b"hunter2").decode()
    for bad in (foreign, encrypt_secret("hunter2")[:-4] + "AAAA", "not a token"):
        with pytest.raises(SecretUnreadable):
            decrypt_secret(bad)


def test_the_public_development_key_is_refused_outside_local_environments():
    with pytest.raises(ValueError, match="SECRETS_ENCRYPTION_KEY"):
        Settings(_env_file=None, app_env="production", session_signing_key="p" * 32, audit_hmac_key="q" * 32)


def test_a_key_that_is_not_a_fernet_key_is_refused():
    with pytest.raises(ValueError, match="Fernet"):
        Settings(_env_file=None, app_env="development", secrets_encryption_key="too short")


def test_a_real_key_is_accepted_in_production():
    key = Fernet.generate_key().decode()
    settings = Settings(
        _env_file=None, app_env="production", session_signing_key="p" * 32, audit_hmac_key="q" * 32,
        secrets_encryption_key=key,
    )
    assert settings.secrets_encryption_key == key
