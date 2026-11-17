from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

MAX_RECOMMENDATIONS = 5
RELATIVE_CUT = 0.5


@dataclass(frozen=True)
class Candidate:
    item_id: str
    tag_weights: Mapping[str, float] = field(default_factory=dict)
    complement_tags: frozenset[str] = frozenset()
    product_id: str | None = None
    pack_size: int | None = None
    price_tier: int = 0


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    score: float


def price_tier(price_cents: int, boundaries: Sequence[int]) -> int:
    if price_cents < 0:
        raise ValueError("price must not be negative")
    if any(boundary < 0 for boundary in boundaries) or list(boundaries) != sorted(boundaries):
        raise ValueError("boundaries must be sorted ascending and non-negative")
    return sum(1 for boundary in boundaries if price_cents >= boundary)


def _reject_duplicate_ids(candidates: list[Candidate]) -> None:
    ids = [candidate.item_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("candidates must have unique item ids")


def _matched_weight(candidate: Candidate, wanted_tags: frozenset[str]) -> float:
    return sum(weight for tag, weight in candidate.tag_weights.items() if tag in wanted_tags)


def _best_first(scored: Mapping[str, float]) -> list[RankedItem]:
    ranked = [RankedItem(item_id, score) for item_id, score in scored.items() if score > 0]
    return sorted(ranked, key=lambda item: (-item.score, item.item_id))


def _cut_and_limit(ranked: list[RankedItem], limit: int) -> list[RankedItem]:
    if not ranked or limit <= 0:
        return []
    floor = ranked[0].score * RELATIVE_CUT
    kept = [item for item in ranked if item.score >= floor]
    return kept[: min(limit, MAX_RECOMMENDATIONS)]


def rank_by_tags(
    candidates: list[Candidate], wanted_tags: frozenset[str], limit: int = MAX_RECOMMENDATIONS
) -> list[RankedItem]:
    _reject_duplicate_ids(candidates)
    scored = {candidate.item_id: _matched_weight(candidate, wanted_tags) for candidate in candidates}
    return _cut_and_limit(_best_first(scored), limit)


def _usable_co_purchase_scores(
    chosen_ids: set[str],
    eligible_ids: set[str],
    co_purchases: Mapping[str, Mapping[str, int]],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for chosen_id in chosen_ids:
        for other_id, count in co_purchases.get(chosen_id, {}).items():
            if other_id in eligible_ids and count > 0:
                scores[other_id] = scores.get(other_id, 0) + count
    return scores


def item_cross_sell(
    chosen: list[Candidate],
    catalog: list[Candidate],
    already_bought: frozenset[str],
    co_purchases: Mapping[str, Mapping[str, int]] | None = None,
    limit: int = MAX_RECOMMENDATIONS,
) -> list[RankedItem]:
    _reject_duplicate_ids(catalog)
    chosen_ids = {item.item_id for item in chosen}
    excluded = chosen_ids | already_bought
    eligible = [item for item in catalog if item.item_id not in excluded]
    eligible_ids = {item.item_id for item in eligible}
    observed = _usable_co_purchase_scores(chosen_ids, eligible_ids, co_purchases or {})
    if observed:
        return _cut_and_limit(_best_first(observed), limit)
    complements = frozenset().union(*(item.complement_tags for item in chosen))
    return rank_by_tags(eligible, complements, limit)


def _next_bigger_pack(current: Candidate, eligible: list[Candidate]) -> Candidate | None:
    if current.product_id is None or current.pack_size is None:
        return None
    bigger = [
        item
        for item in eligible
        if item.product_id == current.product_id
        and item.pack_size is not None
        and item.pack_size > current.pack_size
    ]
    return min(bigger, key=lambda item: (item.pack_size, item.item_id), default=None)


def _best_same_need_one_tier_up(current: Candidate, eligible: list[Candidate]) -> Candidate | None:
    wanted = frozenset(current.tag_weights)
    tier_up = [item for item in eligible if item.price_tier == current.price_tier + 1]
    scored = {item.item_id: _matched_weight(item, wanted) for item in tier_up}
    ranked = _best_first(scored)
    return next((item for item in tier_up if ranked and item.item_id == ranked[0].item_id), None)


def item_upsell(current: Candidate, catalog: list[Candidate], already_bought: frozenset[str]) -> str | None:
    _reject_duplicate_ids(catalog)
    eligible = [
        item
        for item in catalog
        if item.item_id != current.item_id and item.item_id not in already_bought
    ]
    chosen = _next_bigger_pack(current, eligible) or _best_same_need_one_tier_up(current, eligible)
    return chosen.item_id if chosen else None
