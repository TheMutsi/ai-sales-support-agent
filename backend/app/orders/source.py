"""Where orders come from. The rest of the app only knows this interface, so the shop's real
orders API can replace the simulated table without touching the lookup logic (the same shape
as `OtpSender`)."""

import uuid
from typing import Protocol, runtime_checkable

from app.schemas.orders import OrderDetails


@runtime_checkable
class OrderSource(Protocol):
    async def get_order(self, *, tenant_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        """The tenant's order with that id, or None. The tenant is part of the call so an id
        from one shop can never resolve for another. A malformed id is None, not an error."""
        ...
