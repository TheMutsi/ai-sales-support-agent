"""Rejecting or returning an order: what is allowed and what is offered to keep it.

An order that has not shipped can be rejected (cancelled). One that is on its way cannot: it
is returned once it arrives. Before a customer rejects an order worth at least
`RETENTION_MIN_CENTS`, they are offered to keep it for part of the price back to the card, or a
larger part as points. The numbers are computed here, in integer cents, because arithmetic is
not left to the model.
"""

from app.schemas.orders import OrderDetails, OrderStatus, RetentionOffer, ReturnOptions

RETENTION_MIN_CENTS = 5_000
REFUND_PERCENT = 20
CREDIT_PERCENT = 30
POINTS_PER_CENT = 1  # one point is worth one cent in the shop
# Added to the offer the second time, when the customer has declined it once.
GIFT_NAME = "Chai Jelly"
GIFT_DESCRIPTION = "Our thank-you gift for staying with us"
GIFT_VALUE = "$49.99"  # shown struck through, next to "GIFT"
GIFT_IMAGE = "https://cdn.shopify.com/s/files/1/0021/4889/2732/files/chai_jelly_13200.jpg?v=1792189304"


def _percent_of(cents: int, percent: int) -> int:
    """Rounded half up, without floats."""
    return (cents * percent + 50) // 100


def retention_offer(amount_cents: int) -> RetentionOffer | None:
    if amount_cents < RETENTION_MIN_CENTS:
        return None
    return RetentionOffer(
        refund_cents=_percent_of(amount_cents, REFUND_PERCENT),
        credit_points=_percent_of(amount_cents, CREDIT_PERCENT) * POINTS_PER_CENT,
    )


def return_options(order: OrderDetails) -> ReturnOptions:
    if order.retention is not None:  # kept with the offer: it stays as it is
        return ReturnOptions(can_cancel=False, return_after_delivery=False, retention=None)
    open_order = order.status is OrderStatus.OPEN
    in_delivery = order.status is OrderStatus.IN_DELIVERY
    return ReturnOptions(
        can_cancel=open_order,
        return_after_delivery=in_delivery,
        retention=retention_offer(order.amount_cents) if open_order or in_delivery else None,
    )
