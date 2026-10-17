from app.auth.credentials import generate_api_key, generate_secret


def test_api_key_is_recognizably_public_and_unique():
    keys = {generate_api_key() for _ in range(50)}

    assert len(keys) == 50
    assert all(k.startswith("pk_") for k in keys)


def test_secret_has_at_least_256_bits_of_entropy_and_is_unique():
    secrets_ = {generate_secret() for _ in range(50)}

    assert len(secrets_) == 50
    # token_urlsafe(32) encodes 32 random bytes as 43 base64url characters.
    assert all(len(s) >= 43 for s in secrets_)
