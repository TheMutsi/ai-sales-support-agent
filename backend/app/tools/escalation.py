import secrets

_READ_ALOUD_SAFE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_LENGTH = 8


def new_reference() -> str:
    return "MF-" + "".join(secrets.choice(_READ_ALOUD_SAFE_ALPHABET) for _ in range(_LENGTH))
