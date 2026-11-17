from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class SecretUnreadable(Exception):
    pass


def encrypt_secret(plain: str) -> str:
    return Fernet(get_settings().secrets_encryption_key).encrypt(plain.encode()).decode()


def decrypt_secret(stored: str) -> str:
    try:
        return Fernet(get_settings().secrets_encryption_key).decrypt(stored.encode()).decode()
    except InvalidToken as problem:
        raise SecretUnreadable("stored secret cannot be decrypted with the current key") from problem
