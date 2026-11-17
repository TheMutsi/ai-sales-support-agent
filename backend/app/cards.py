from app.business.returns import (
    CREDIT_PERCENT,
    GIFT_COMPARE_PRICE,
    GIFT_DESCRIPTION,
    GIFT_IMAGE,
    GIFT_NAME,
    REFUND_PERCENT,
)
from app.schemas.cards import (
    ActionCard,
    Card,
    CardAction,
    CardImage,
    DividerCard,
    ProductCard,
    RecommendationCard,
    RecommendationTemplate,
)
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


def recommendation_heading(label: str) -> DividerCard:
    return DividerCard(id=f"heading-{label.lower().replace(' ', '-')}", label=label, variant="heading")


def recommendation_card(
    *,
    item_id: str,
    title: str,
    image_url: str | None = None,
    price_cents: int | None = None,
    compare_price_cents: int | None = None,
    description: str | None = None,
    rating: float | None = None,
    url: str | None = None,
    offer_label: str | None = None,
    why: str | None = None,
    template: RecommendationTemplate = RecommendationTemplate.PRODUCT_CARD,
) -> RecommendationCard:
    return RecommendationCard(
        id=f"recommendation-{item_id}",
        template=template,
        title=title,
        description=description,
        image=None if image_url is None else CardImage(url=image_url, alt=title),
        rating=rating,
        url=url,
        price=None if price_cents is None else _dollars(price_cents),
        compare_price=None if compare_price_cents is None else _dollars(compare_price_cents),
        offer_label=offer_label,
        why=why,
    )


def _name(order: OrderDetails) -> str:
    return order.item_name or f"{order.plan_slug.capitalize()} plan"


def product_card(order: OrderDetails) -> ProductCard:
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
    return [
        ActionCard(
            id="offer-refund",
            title=f"{_dollars(offer.refund_cents)} ({REFUND_PERCENT}%) back to your card",
            subtitle=f"Keep your order and get {REFUND_PERCENT}% of its price back",
            badge=f"{REFUND_PERCENT}% back",
            message=f"I'll take the {_dollars(offer.refund_cents)} refund to my card",
            action=CardAction.TAKE_REFUND,
        ),
        ActionCard(
            id="offer-credits",
            title=f"{_dollars(offer.credit_cents)} ({CREDIT_PERCENT}%) in credits",
            subtitle=f"Keep your order and get {CREDIT_PERCENT}% of its price as credit to spend here",
            badge=f"{CREDIT_PERCENT}% in credits",
            message=f"I'll take the {_dollars(offer.credit_cents)} in credits",
            action=CardAction.TAKE_CREDITS,
        ),
    ]


def gift_card(badge: str = "Free gift") -> ProductCard:
    return ProductCard(
        id="gift",
        name=GIFT_NAME,
        subtitle=GIFT_DESCRIPTION,
        price="GIFT",
        compare_price=GIFT_COMPARE_PRICE,
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
                    action=CardAction.DECLINE_OFFER,
                ),
            ]
        case ReturnOutcome.FINAL_OFFER if order is not None and offer is not None:
            return [
                gift_card(),
                DividerCard(id="gift-plus", label="+"),
                *_option_cards(offer),
                ActionCard(
                    id="offer-reject",
                    title="No, cancel my order",
                    message="No, cancel my order",
                    action=CardAction.DECLINE_OFFER,
                ),
            ]
        case ReturnOutcome.KEPT_WITH_REFUND | ReturnOutcome.KEPT_WITH_CREDITS:
            return [gift_card("Your gift")] if result.receipt and result.receipt.gift else []
        case ReturnOutcome.CONFIRM_ORDER if order is not None:
            return [
                product_card(order),
                ActionCard(
                    id="check-yes", title="Yes, this one", message="Yes, I want to cancel this order",
                    action=CardAction.CONFIRM_ORDER,
                ),
                ActionCard(
                    id="check-no", title="No, keep my order", message="No, keep my order",
                    action=CardAction.KEEP_ORDER,
                ),
            ]
        case ReturnOutcome.CONFIRM_CANCEL if order is not None:
            return [
                product_card(order),
                ActionCard(
                    id="confirm-yes", title="Yes, cancel it", message="Yes, cancel it",
                    action=CardAction.CONFIRM_CANCEL,
                ),
                ActionCard(
                    id="confirm-no", title="No, keep my order", message="No, keep my order",
                    action=CardAction.KEEP_ORDER,
                ),
            ]
        case ReturnOutcome.CHOOSE_ORDER:
            return [
                ActionCard(
                    id=f"choose-{o.order_id}",
                    title=f"{_name(o)}, {_dollars(o.amount_cents)}",
                    subtitle=_STATUS_BADGE.get(o.status, o.status.value),
                    message=f"I mean {_order_label(o)}",
                    action=CardAction.CHOOSE_ORDER,
                    order_id=o.order_id,
                )
                for o in result.candidates
            ]
    return []


def cards_for(final_state: dict) -> list[Card]:
    if final_state.get("return_result") is not None:
        return _return_cards(final_state["return_result"])
    if final_state.get("customer_orders"):
        return [product_card(order) for order in final_state["customer_orders"]]
    return []
