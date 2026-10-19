"""Where orders come from. The rest of the app only knows this interface, so the shop's real
orders API can replace the simulated table without touching the lookup logic (the same shape
as `OtpSender`)."""

import uuid
from typing import Protocol, runtime_checkable

from app.schemas.orders import OrderDetails, RetentionChoice, RetentionReceipt


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
        not exist, can no longer be cancelled, or was already kept with the retention offer
        (keeping an order means it is not cancelled); the state is checked under a lock at the
        moment of the change, so two requests cannot both succeed."""
        ...

    async def keep_order_with_retention(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_id: str,
        choice: RetentionChoice,
    ) -> RetentionReceipt | None:
        """Records that the customer kept the order for the refund or the points the rules give
        for its amount (computed here from the order itself, never taken from the caller). At
        most once per order, only while it is open or in delivery and only for an order that
        qualifies; None otherwise. Moves no money in the simulation."""
        ...
