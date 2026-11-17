import secrets


def generate_api_key() -> str:
    return f"pk_{secrets.token_urlsafe(16)}"


def generate_secret() -> str:
    return secrets.token_urlsafe(32)
