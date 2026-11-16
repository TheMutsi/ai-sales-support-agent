from app.schemas.orders import OrderDetails, OrderStatus, RetentionOffer, ReturnOptions

RETENTION_MIN_CENTS = 5_000
REFUND_PERCENT = 20
CREDIT_PERCENT = 30
GIFT_NAME = "Shapermint Essentials Everyday Wireless Jelly Bra"
GIFT_DESCRIPTION = "Our thank-you gift for staying with us"
GIFT_COMPARE_PRICE = "$49.99"
GIFT_IMAGE = "https://cdn.shopify.com/s/files/1/0021/4889/2732/files/chai_jelly_13200.jpg?v=1792189304"


def _percent_rounded_half_up(cents: int, percent: int) -> int:
    return (cents * percent + 50) // 100


def retention_offer(amount_cents: int) -> RetentionOffer | None:
    if amount_cents < RETENTION_MIN_CENTS:
        return None
    return RetentionOffer(
        refund_cents=_percent_rounded_half_up(amount_cents, REFUND_PERCENT),
        credit_cents=_percent_rounded_half_up(amount_cents, CREDIT_PERCENT),
    )


def return_options(order: OrderDetails) -> ReturnOptions:
    kept_with_an_offer = order.retention is not None
    if kept_with_an_offer:
        return ReturnOptions(can_cancel=False, return_after_delivery=False, retention=None)
    open_order = order.status is OrderStatus.OPEN
    in_delivery = order.status is OrderStatus.IN_DELIVERY
    return ReturnOptions(
        can_cancel=open_order,
        return_after_delivery=in_delivery,
        retention=retention_offer(order.amount_cents) if open_order or in_delivery else None,
    )
