"""What an order looks like to the rest of the app, wherever it comes from.

The shop's orders will come from its own API; this is the shape we depend on, so a real
client can replace the simulated one without touching who may see an order.
"""

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# Strict on purpose, like the other identity inputs: it arrives from a stranger and ends up in
# a query and a log line. ASCII only; `fullmatch` and not `$`, which lets a trailing newline by.
ORDER_ID_PATTERN = r"^[A-Za-z0-9]{20}$"
_ORDER_ID = re.compile(r"[A-Za-z0-9]{20}")


def is_valid_order_id(value: str) -> bool:
    return _ORDER_ID.fullmatch(value) is not None


class OrderStatus(StrEnum):
    PAID = "paid"
    PENDING = "pending"
    REFUNDED = "refunded"
    # An order not shipped yet, which the customer can still reject.
    OPEN = "open"
    # On its way: it cannot be rejected, only returned once it arrives.
    IN_DELIVERY = "in_delivery"
    CANCELLED = "cancelled"


class OrderDetails(BaseModel):
    """A purchase of a plan: an order for MewFlow is a sign-up or a change of plan."""

    order_id: str = Field(pattern=ORDER_ID_PATTERN)
    # The second factor to identify with is compared against this, by our code (never by the
    # source), so the rule lives in one place whoever provides the orders.
    customer_email: str
    plan_slug: str
    amount_cents: int
    currency: str
    status: OrderStatus
    created_at: datetime
    # What was bought, when it is not just a plan: a name and picture URLs (the first is the main one).
    item_name: str | None = None
    item_images: list[str] = Field(default_factory=list)
    # Set when the customer kept this order with the retention offer (it then stays as it is).
    retention: "RetentionReceipt | None" = None


class RetentionChoice(StrEnum):
    """What a customer who wants to reject an order can take instead of rejecting it."""

    REFUND = "refund"  # part of the price back to the card
    CREDITS = "credits"  # a larger part as points to spend in the shop
    NEXT_ORDER_FREE = "next_order_free"  # their next order costs nothing (a coupon code)


class RetentionOffer(BaseModel):
    refund_cents: int
    credit_points: int


class ReturnOptions(BaseModel):
    """What may be done with an order a customer does not want, decided by the rules and never
    by the model."""

    can_cancel: bool  # not shipped yet: rejecting it cancels it
    return_after_delivery: bool  # on its way: it cannot be rejected, it is returned once received
    retention: RetentionOffer | None  # offered before rejecting, for orders of a certain value


class ReturnStage(StrEnum):
    OFFER = "offer"  # the customer was offered to keep the order for a refund or points
    FINAL_OFFER = "final_offer"  # they declined the offer and were offered it again, with a gift
    CONFIRM = "confirm"  # the customer was asked to confirm cancelling it


class PendingReturn(BaseModel):
    """A return the customer is in the middle of: kept on the conversation between turns."""

    order_id: str
    stage: ReturnStage


class ReturnOutcome(StrEnum):
    NOTHING_TO_RETURN = "nothing_to_return"
    CHOOSE_ORDER = "choose_order"
    OFFER = "offer"
    FINAL_OFFER = "final_offer"
    CONFIRM_CANCEL = "confirm_cancel"
    RETURN_LATER = "return_later"
    CANCELLED = "cancelled"
    KEPT_WITH_REFUND = "kept_with_refund"
    KEPT_WITH_CREDITS = "kept_with_credits"
    KEPT_WITH_FREE_ORDER = "kept_with_free_order"
    KEPT_AS_IS = "kept_as_is"
    NOT_AVAILABLE = "not_available"  # the order changed under us: nothing was done


class RetentionReceipt(BaseModel):
    """What was recorded when the customer took the offer and kept the order."""

    order_id: str
    choice: RetentionChoice
    refund_cents: int | None = None
    credit_points: int | None = None
    coupon_code: str | None = None  # for a free next order
    gift: str | None = None  # a free gift, when the offer was taken at the last chance


class ReturnResult(BaseModel):
    """What the `order_return` step did or needs the writer to ask, with the numbers already
    worked out. The writer may say what is here and nothing else."""

    outcome: ReturnOutcome
    order: OrderDetails | None = None
    candidates: list[OrderDetails] = []
    offer: RetentionOffer | None = None
    receipt: RetentionReceipt | None = None


OrderDetails.model_rebuild()  # resolves its reference to RetentionReceipt, declared below it
