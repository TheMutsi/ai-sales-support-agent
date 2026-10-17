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
