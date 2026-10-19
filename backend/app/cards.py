"""What cards a turn shows, decided from the state the graph ended with.

Deterministic like the rest of the facts: a card appears because a step really produced what it
shows (an offer the rules made, an order that was read), so the model cannot invent one or
leave out a number. The text of the reply and the cards come from the same state.
"""

from app.business.returns import GIFT_DESCRIPTION, GIFT_NAME
from app.schemas.cards import ActionCard, Card, CardImage, CouponCard, DividerCard, ProductCard
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    RetentionOffer,
    ReturnOutcome,
    ReturnResult,
)

_STATUS_BADGE = {
    OrderStatus.OPEN: "Open",
    OrderStatus.IN_DELIVERY: "In delivery",
    OrderStatus.CANCELLED: "Cancelled",
    OrderStatus.PAID: "Paid",
    OrderStatus.PENDING: "Pending",
    OrderStatus.REFUNDED: "Refunded",
}


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def product_card(order: OrderDetails) -> ProductCard:
    name = f"{order.plan_slug.capitalize()} plan"
    return ProductCard(
        id=order.order_id,
        name=name,
        price=_dollars(order.amount_cents),
        subtitle=f"Order placed {order.created_at:%b %d, %Y}",
        badge=_STATUS_BADGE.get(order.status, order.status.value),
        image=CardImage(url=f"/api/assets/products/{order.plan_slug}.svg", alt=name),
    )


def _option_cards(offer: RetentionOffer) -> list[Card]:
    """The three things a customer can take to keep an order."""
    return [
        ActionCard(
            id="offer-refund",
            title=f"{_dollars(offer.refund_cents)} back to your card",
            subtitle="Keep your order and get 20% of its price back",
            badge="20% back",
            message=f"I'll take the {_dollars(offer.refund_cents)} refund to my card",
        ),
        ActionCard(
            id="offer-points",
            title=f"{offer.credit_points:,} points",
            subtitle="Keep your order and get 30% of its price as points",
            badge="30% in points",
            message=f"I'll take the {offer.credit_points:,} points",
        ),
        ActionCard(
            id="offer-free",
            title="Your next order, free",
            subtitle="Keep your order and your next one is on us",
            badge="Free",
            message="I'll take the next order free",
        ),
    ]


def gift_card(badge: str = "Free gift") -> ProductCard:
    return ProductCard(
        id="gift",
        name=GIFT_NAME,
        subtitle=GIFT_DESCRIPTION,
        price="FREE",
        badge=badge,
        image=CardImage(url="/api/assets/products/gift.svg", alt=GIFT_NAME),
    )


def _order_label(order: OrderDetails) -> str:
    return f"the {order.plan_slug.capitalize()} plan order of {_dollars(order.amount_cents)} placed {order.created_at:%b %d}"


def _return_cards(result: ReturnResult) -> list[Card]:
    order, offer = result.order, result.offer
    match result.outcome:
        case ReturnOutcome.OFFER if order is not None and offer is not None:
            return [
                product_card(order),
                *_option_cards(offer),
                ActionCard(
                    id="offer-reject",
                    title="No thanks",
                    subtitle="I still want to cancel it",
                    message="No thanks, I want to cancel it",
                ),
            ]
        case ReturnOutcome.FINAL_OFFER if order is not None and offer is not None:
            # The gift and, below a "+", the same three options: both things at once.
            return [
                gift_card(),
                DividerCard(id="gift-plus", label="+"),
                *_option_cards(offer),
                ActionCard(
                    id="offer-reject",
                    title="No, cancel my order",
                    message="No, cancel my order",
                ),
            ]
        case ReturnOutcome.KEPT_WITH_REFUND | ReturnOutcome.KEPT_WITH_CREDITS | ReturnOutcome.KEPT_WITH_FREE_ORDER:
            receipt = result.receipt
            cards: list[Card] = []
            if receipt and receipt.coupon_code:
                cards.append(
                    CouponCard(
                        id=f"coupon-{receipt.coupon_code}",
                        code=receipt.coupon_code,
                        title="Your next order is free",
                        subtitle="Use this code at checkout",
                    )
                )
            if receipt and receipt.gift:
                cards.append(gift_card("Your gift"))
            return cards
        case ReturnOutcome.CONFIRM_CANCEL if order is not None:
            return [
                product_card(order),
                ActionCard(id="confirm-yes", title="Yes, cancel it", message="Yes, cancel it"),
                ActionCard(id="confirm-no", title="No, keep my order", message="No, keep my order"),
            ]
        case ReturnOutcome.CHOOSE_ORDER:
            return [
                ActionCard(
                    id=f"choose-{o.order_id}",
                    title=f"{o.plan_slug.capitalize()} plan, {_dollars(o.amount_cents)}",
                    subtitle=_STATUS_BADGE.get(o.status, o.status.value),
                    message=f"I mean {_order_label(o)}",
                )
                for o in result.candidates
            ]
    return []


def cards_for(final_state: dict) -> list[Card]:
    """Cards for the reply this state produced. They come from what the steps did, so they stand
    even if a guardrail rewrote the text around them."""
    if final_state.get("return_result") is not None:
        return _return_cards(final_state["return_result"])
    if final_state.get("customer_orders"):
        return [product_card(order) for order in final_state["customer_orders"]]
    return []
