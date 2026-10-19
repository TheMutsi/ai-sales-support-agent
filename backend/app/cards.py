"""What cards a turn shows, decided from the state the graph ended with.

Deterministic like the rest of the facts: a card appears because a step really produced what it
shows (an offer the rules made, an order that was read), so the model cannot invent one or
leave out a number. The text of the reply and the cards come from the same state.
"""

from app.schemas.cards import ActionCard, Card, CardImage, ProductCard
from app.schemas.orders import OrderDetails, OrderStatus, ReturnOutcome, ReturnResult

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


def _return_cards(result: ReturnResult) -> list[Card]:
    order, offer = result.order, result.offer
    match result.outcome:
        case ReturnOutcome.OFFER if order is not None and offer is not None:
            return [
                product_card(order),
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
                    id="offer-reject",
                    title="No thanks",
                    subtitle="Reject the order anyway",
                    message="No thanks, I want to reject it anyway",
                ),
            ]
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
                    message=f"I mean order {o.order_id}",
                )
                for o in result.candidates
            ]
    return []


def cards_for(final_state: dict) -> list[Card]:
    """Cards for the reply this state produced. None for a reply the guardrail replaced, whose
    text no longer matches what the step meant to say."""
    if final_state.get("return_result") is not None:
        return _return_cards(final_state["return_result"])
    if final_state.get("customer_orders"):
        return [product_card(order) for order in final_state["customer_orders"]]
    return []
