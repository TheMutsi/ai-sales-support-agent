from dataclasses import dataclass
from enum import StrEnum


class OfferKind(StrEnum):
    PACK = "pack"
    PERCENT = "percent"
    BUNDLE = "bundle"


@dataclass(frozen=True)
class Offer:
    kind: OfferKind
    percent: int = 0
    quantity: int = 1
    price_cents: int = 0
    compare_at_cents: int = 0
    active: bool = True


@dataclass(frozen=True)
class OfferDisplay:
    price_cents: int
    compare_price_cents: int | None
    discount_percent: int


def _percent_rounded_half_up(cents: int, percent: int) -> int:
    return (cents * percent + 50) // 100


def _reject_invalid(offer: Offer) -> None:
    if offer.price_cents < 0:
        raise ValueError("offer price must not be negative")
    if offer.kind is OfferKind.PERCENT and not 0 <= offer.percent <= 100:
        raise ValueError("offer percent must be between 0 and 100")
    if offer.kind is OfferKind.PACK and (offer.price_cents <= 0 or offer.quantity <= 0):
        raise ValueError("pack offer needs a positive price and quantity")


def _price_and_compare_price(base_price_cents: int, offer: Offer) -> tuple[int, int]:
    if offer.kind is OfferKind.PERCENT and offer.compare_at_cents > 0:
        return offer.price_cents, offer.compare_at_cents
    if offer.kind is OfferKind.PERCENT:
        discount = _percent_rounded_half_up(base_price_cents, offer.percent)
        return base_price_cents - discount, base_price_cents
    if offer.kind is OfferKind.PACK:
        return offer.price_cents, base_price_cents * offer.quantity
    return offer.price_cents, offer.compare_at_cents


def _discount_percent(price_cents: int, compare_price_cents: int) -> int:
    saved_cents = compare_price_cents - price_cents
    return (saved_cents * 100 + compare_price_cents // 2) // compare_price_cents


def best_offer_display(base_price_cents: int, offers: list[Offer]) -> OfferDisplay:
    if base_price_cents < 0:
        raise ValueError("base price must not be negative")
    best: OfferDisplay | None = None
    for offer in offers:
        if not offer.active:
            continue
        _reject_invalid(offer)
        price_cents, compare_price_cents = _price_and_compare_price(base_price_cents, offer)
        if compare_price_cents <= 0 or price_cents >= compare_price_cents:
            continue
        shown = OfferDisplay(
            price_cents, compare_price_cents, _discount_percent(price_cents, compare_price_cents)
        )
        if best is None or shown.discount_percent > best.discount_percent:
            best = shown
    return best or OfferDisplay(base_price_cents, None, 0)
