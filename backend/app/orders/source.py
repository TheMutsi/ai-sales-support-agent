"""Where orders come from. The rest of the app only knows this interface, so the shop's real
orders API can replace the simulated table without touching the lookup logic (the same shape
as `OtpSender`)."""

import uuid
from typing import Protocol, runtime_checkable

from app.schemas.orders import OrderDetails, RetentionChoice, RetentionOffer, RetentionReceipt


@runtime_checkable
class OrderSource(Protocol):
    async def get_order(self, *, tenant_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        """The tenant's order with that id, or None. The tenant is part of the call so an id
        from one shop can never resolve for another. A malformed id is None, not an error."""
        ...

    async def list_orders(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, limit: int = 10
    ) -> list[OrderDetails]:
        """The customer's most recent orders, newest first. Only for a customer the session
        already proved (never taken from a message); another shop's customer gives nothing."""
        ...

    async def cancel_order(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, order_id: str
    ) -> OrderDetails | None:
        """Cancels the customer's order if it has not shipped. None when it is not theirs, does
        not exist or can no longer be cancelled; the status is checked at the moment of the
        change, so two requests cannot both succeed."""
        ...

    async def keep_order_with_retention(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_id: str,
        choice: RetentionChoice,
        offer: RetentionOffer,
    ) -> RetentionReceipt | None:
        """Records that the customer kept the order for the refund or the points of `offer`. At
        most once per order, and only while it is open or in delivery; None otherwise. Moves no
        money in the simulation."""
        ...
