"""Encryption of credentials kept in the database.

A tenant's SMTP password has to be read back to log in to the mail server, so it cannot be
hashed; it is encrypted instead, with a key that lives in the environment (`SECRETS_ENCRYPTION_KEY`)
and never in the database. A dump of the database alone then holds only ciphertext. Fernet
(AES-128-CBC plus an HMAC) is authenticated: a tampered or foreign value fails to decrypt rather
than yielding garbage.

Limits: whoever has both the database and the environment reads everything, and replacing the key
makes every stored value unreadable (`SecretUnreadable`) until it is entered again. Rotating the
key without re-entering values would need a re-encryption step, which is not built.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class SecretUnreadable(Exception):
    """The stored value was not encrypted with the current key, or was altered."""


def encrypt_secret(plain: str) -> str:
    return Fernet(get_settings().secrets_encryption_key).encrypt(plain.encode()).decode()


def decrypt_secret(stored: str) -> str:
    try:
        return Fernet(get_settings().secrets_encryption_key).decrypt(stored.encode()).decode()
    except InvalidToken as problem:
        raise SecretUnreadable("stored secret cannot be decrypted with the current key") from problem
