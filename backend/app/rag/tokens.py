import math

CHARACTERS_PER_TOKEN = 3
DOCUMENT_TOKEN_LIMIT = 3000


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARACTERS_PER_TOKEN)
