from collections.abc import Collection, Sequence

from app.business.recommendations import RankedItem
from app.business.tag_registry import normalize_slug

MAX_QUERY_TAGS = 5
WEAK_SCORE = 0.5
RECIPROCAL_RANK_FUSION_K = 60


def validate_selection(slugs: Sequence[str], registry: Collection[str]) -> list[str]:
    chosen: list[str] = []
    for raw in slugs:
        try:
            slug = normalize_slug(raw)
        except ValueError:
            continue
        if slug in registry and slug not in chosen:
            chosen.append(slug)
    return chosen[:MAX_QUERY_TAGS]


def is_weak(ranked: Sequence[RankedItem]) -> bool:
    return not ranked or ranked[0].score < WEAK_SCORE


def fuse_rankings(rankings: Sequence[Sequence[str]]) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1 / (RECIPROCAL_RANK_FUSION_K + position)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
