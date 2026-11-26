import math
import re
import unicodedata
from collections.abc import Mapping, Sequence

NEAR_DUPLICATE_SIMILARITY = 0.9
MAX_SLUG_LENGTH = 40


def normalize_slug(raw: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:MAX_SLUG_LENGTH].strip("-")
    if not slug:
        raise ValueError("a tag needs at least one letter or digit")
    return slug


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same size")
    norm = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(y * y for y in right))
    if norm == 0:
        return 0.0
    return sum(x * y for x, y in zip(left, right)) / norm


def find_near_duplicate(
    vector: Sequence[float],
    registry: Mapping[str, Sequence[float]],
    threshold: float = NEAR_DUPLICATE_SIMILARITY,
) -> str | None:
    best_slug: str | None = None
    best_similarity = threshold
    for slug in sorted(registry):
        similarity = cosine_similarity(vector, registry[slug])
        if similarity >= best_similarity and (best_slug is None or similarity > best_similarity):
            best_slug, best_similarity = slug, similarity
    return best_slug
