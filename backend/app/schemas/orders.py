import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

ORDER_ID_PATTERN = r"^[A-Za-z0-9]{20}$"
_ORDER_ID = re.compile(r"[A-Za-z0-9]{20}")


def is_valid_order_id(value: str) -> bool:
    return _ORDER_ID.fullmatch(value) is not None


class OrderStatus(StrEnum):
    PAID = "paid"
    PENDING = "pending"
    REFUNDED = "refunded"
    OPEN = "open"
    IN_DELIVERY = "in_delivery"
    CANCELLED = "cancelled"


class OrderDetails(BaseModel):
    order_id: str = Field(pattern=ORDER_ID_PATTERN)
    customer_email: str
    plan_slug: str
    amount_cents: int
    currency: str
    status: OrderStatus
    created_at: datetime
    item_name: str | None = None
    item_images: list[str] = Field(default_factory=list)
    retention: "RetentionReceipt | None" = None


class RetentionChoice(StrEnum):
    REFUND = "refund"
    CREDITS = "credits"


class RetentionOffer(BaseModel):
    refund_cents: int
    credit_cents: int


class ReturnOptions(BaseModel):
    can_cancel: bool
    return_after_delivery: bool
    retention: RetentionOffer | None


class ReturnStage(StrEnum):
    CHECK = "check"
    OFFER = "offer"
    FINAL_OFFER = "final_offer"
    CONFIRM = "confirm"


class PendingReturn(BaseModel):
    order_id: str
    stage: ReturnStage


class ReturnOutcome(StrEnum):
    NOTHING_TO_RETURN = "nothing_to_return"
    CHOOSE_ORDER = "choose_order"
    CONFIRM_ORDER = "confirm_order"
    OFFER = "offer"
    FINAL_OFFER = "final_offer"
    CONFIRM_CANCEL = "confirm_cancel"
    RETURN_LATER = "return_later"
    CANCELLED = "cancelled"
    KEPT_WITH_REFUND = "kept_with_refund"
    KEPT_WITH_CREDITS = "kept_with_credits"
    KEPT_AS_IS = "kept_as_is"
    NOT_AVAILABLE = "not_available"
    ESCALATED = "escalated"


class RetentionReceipt(BaseModel):
    order_id: str
    choice: RetentionChoice
    refund_cents: int | None = None
    credit_cents: int | None = None
    gift: str | None = None


class ReturnResult(BaseModel):
    outcome: ReturnOutcome
    order: OrderDetails | None = None
    candidates: list[OrderDetails] = []
    offer: RetentionOffer | None = None
    receipt: RetentionReceipt | None = None


OrderDetails.model_rebuild()
