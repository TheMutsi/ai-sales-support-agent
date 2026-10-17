"""Generates the credentials we issue to a tenant when it signs up.

The API key is public (it appears in the widget's script URL), so it only has to
be unique and recognizable. The secret is what actually authenticates the shop's
tokens: 32 random bytes from the OS CSPRNG, shown to the shop once.
"""

import secrets


def generate_api_key() -> str:
    return f"pk_{secrets.token_urlsafe(16)}"


def generate_secret() -> str:
    return secrets.token_urlsafe(32)
