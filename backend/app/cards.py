"""What cards a turn shows, decided from the state the graph ended with.

Deterministic like the rest of the facts: a card appears because a step really produced what it
shows (an offer the rules made, an order that was read), so the model cannot invent one or
leave out a number. The text of the reply and the cards come from the same state.
"""

from app.business.returns import (
    CREDIT_PERCENT,
    GIFT_DESCRIPTION,
    GIFT_IMAGE,
    GIFT_NAME,
    GIFT_VALUE,
    REFUND_PERCENT,
)
from app.schemas.cards import ActionCard, Card, CardImage, DividerCard, ProductCard
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


def _name(order: OrderDetails) -> str:
    """What the order is for: the item when it says so, else its plan."""
    return order.item_name or f"{order.plan_slug.capitalize()} plan"


def product_card(order: OrderDetails) -> ProductCard:
    """The order as a product: what was bought when the order says so, else its plan."""
    name = _name(order)
    if order.item_images:
        pictures = [CardImage(url=url, alt=name) for url in order.item_images]
    else:
        pictures = [CardImage(url=f"/api/assets/products/{order.plan_slug}.svg", alt=name)]
    return ProductCard(
        id=order.order_id,
        name=name,
        price=_dollars(order.amount_cents),
        subtitle=f"Order placed {order.created_at:%b %d, %Y}",
        badge=_STATUS_BADGE.get(order.status, order.status.value),
        image=pictures[0],
        more_images=pictures[1:],
    )


def _option_cards(offer: RetentionOffer) -> list[Card]:
    """The two things a customer can take to keep an order, each with its amount and its share."""
    return [
        ActionCard(
            id="offer-refund",
            title=f"{_dollars(offer.refund_cents)} ({REFUND_PERCENT}%) back to your card",
            subtitle=f"Keep your order and get {REFUND_PERCENT}% of its price back",
            badge=f"{REFUND_PERCENT}% back",
            message=f"I'll take the {_dollars(offer.refund_cents)} refund to my card",
        ),
        ActionCard(
            id="offer-credits",
            title=f"{_dollars(offer.credit_cents)} ({CREDIT_PERCENT}%) in credits",
            subtitle=f"Keep your order and get {CREDIT_PERCENT}% of its price as credit to spend here",
            badge=f"{CREDIT_PERCENT}% in credits",
            message=f"I'll take the {_dollars(offer.credit_cents)} in credits",
        ),
    ]


def gift_card(badge: str = "Free gift") -> ProductCard:
    return ProductCard(
        id="gift",
        name=GIFT_NAME,
        subtitle=GIFT_DESCRIPTION,
        price="GIFT",
        compare_price=GIFT_VALUE,
        badge=badge,
        image=CardImage(url=GIFT_IMAGE, alt=GIFT_NAME),
    )


def _order_label(order: OrderDetails) -> str:
    return f"the {_name(order)} order of {_dollars(order.amount_cents)} placed {order.created_at:%b %d}"


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
        case ReturnOutcome.KEPT_WITH_REFUND | ReturnOutcome.KEPT_WITH_CREDITS:
            # What was taken is stated in the reply; the gift, if it came with it, is shown again.
            return [gift_card("Your gift")] if result.receipt and result.receipt.gift else []
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
                    title=f"{_name(o)}, {_dollars(o.amount_cents)}",
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
