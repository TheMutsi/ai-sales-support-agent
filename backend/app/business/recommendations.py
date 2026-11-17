from collections.abc import Mapping
from dataclasses import dataclass, field

MAX_RECOMMENDATIONS = 5
RELATIVE_CUT = 0.5


@dataclass(frozen=True)
class Candidate:
    item_id: str
    tag_weights: Mapping[str, int] = field(default_factory=dict)
    complement_tags: frozenset[str] = frozenset()
    product_id: str | None = None
    pack_size: int = 1
    price_tier: int = 1


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    score: int


def _matched_weight(candidate: Candidate, wanted_tags: frozenset[str]) -> int:
    return sum(weight for tag, weight in candidate.tag_weights.items() if tag in wanted_tags)


def _best_first(scored: dict[str, int]) -> list[RankedItem]:
    ranked = [RankedItem(item_id, score) for item_id, score in scored.items() if score > 0]
    return sorted(ranked, key=lambda item: (-item.score, item.item_id))


def _cut_and_limit(ranked: list[RankedItem], limit: int) -> list[RankedItem]:
    if not ranked:
        return []
    floor = ranked[0].score * RELATIVE_CUT
    kept = [item for item in ranked if item.score >= floor]
    return kept[: max(1, min(limit, MAX_RECOMMENDATIONS))]


def rank_by_tags(
    candidates: list[Candidate], wanted_tags: frozenset[str], limit: int = MAX_RECOMMENDATIONS
) -> list[RankedItem]:
    scored = {candidate.item_id: _matched_weight(candidate, wanted_tags) for candidate in candidates}
    return _cut_and_limit(_best_first(scored), limit)


def _co_purchase_scores(
    chosen_ids: set[str], co_purchases: Mapping[str, Mapping[str, int]]
) -> dict[str, int]:
    scores: dict[str, int] = {}
    for chosen_id in chosen_ids:
        for other_id, count in co_purchases.get(chosen_id, {}).items():
            scores[other_id] = scores.get(other_id, 0) + count
    return scores


def cross_sell(
    chosen: list[Candidate],
    catalog: list[Candidate],
    already_bought: frozenset[str],
    co_purchases: Mapping[str, Mapping[str, int]] | None = None,
    limit: int = MAX_RECOMMENDATIONS,
) -> list[RankedItem]:
    chosen_ids = {item.item_id for item in chosen}
    excluded = chosen_ids | already_bought
    eligible = [item for item in catalog if item.item_id not in excluded]
    observed = _co_purchase_scores(chosen_ids, co_purchases or {})
    if any(count > 0 for count in observed.values()):
        eligible_ids = {item.item_id for item in eligible}
        scored = {item_id: count for item_id, count in observed.items() if item_id in eligible_ids}
        return _cut_and_limit(_best_first(scored), limit)
    complements = frozenset().union(*(item.complement_tags for item in chosen))
    return rank_by_tags(eligible, complements, limit)


def _next_bigger_pack(current: Candidate, eligible: list[Candidate]) -> Candidate | None:
    bigger = [
        item
        for item in eligible
        if current.product_id is not None
        and item.product_id == current.product_id
        and item.pack_size > current.pack_size
    ]
    return min(bigger, key=lambda item: (item.pack_size, item.item_id), default=None)


def _best_same_need_one_tier_up(current: Candidate, eligible: list[Candidate]) -> Candidate | None:
    wanted = frozenset(current.tag_weights)
    tier_up = [item for item in eligible if item.price_tier == current.price_tier + 1]
    scored = {item.item_id: _matched_weight(item, wanted) for item in tier_up}
    ranked = _best_first(scored)
    return next((item for item in tier_up if ranked and item.item_id == ranked[0].item_id), None)


def upsell(current: Candidate, catalog: list[Candidate], already_bought: frozenset[str]) -> str | None:
    eligible = [
        item
        for item in catalog
        if item.item_id != current.item_id and item.item_id not in already_bought
    ]
    chosen = _next_bigger_pack(current, eligible) or _best_same_need_one_tier_up(current, eligible)
    return chosen.item_id if chosen else None
