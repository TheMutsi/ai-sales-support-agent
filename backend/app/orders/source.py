import uuid
from typing import Protocol, runtime_checkable

from app.schemas.orders import OrderDetails, RetentionChoice, RetentionReceipt


@runtime_checkable
class OrderSource(Protocol):
    async def get_order(self, *, tenant_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        ...

    async def list_orders(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, limit: int = 10
    ) -> list[OrderDetails]:
        ...

    async def cancel_order(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, order_id: str
    ) -> OrderDetails | None:
        ...

    async def keep_order_with_retention(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_id: str,
        choice: RetentionChoice,
        with_gift: bool = False,
    ) -> RetentionReceipt | None:
        ...
