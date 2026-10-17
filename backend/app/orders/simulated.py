"""A stand-in for the shop's orders API, backed by the `orders` table.

The call is async because the real one will be a network request; the query itself is
synchronous, so it runs in a worker thread instead of blocking the event loop.
"""

import asyncio
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session, joinedload

from app.db.models import Customer, Order
from app.schemas.orders import OrderDetails, OrderStatus, is_valid_order_id


class SimulatedOrderSource:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def get_order(self, *, tenant_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        if not is_valid_order_id(order_id):
            return None
        return await asyncio.to_thread(self._read, tenant_id, order_id)

    def _read(self, tenant_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        with self._session_factory() as db:
            order = (
                db.query(Order)
                .join(Customer, Order.customer_id == Customer.id)
                .options(joinedload(Order.customer), joinedload(Order.plan))
                .filter(Customer.tenant_id == tenant_id, Order.order_id == order_id)
                .one_or_none()
            )
            if order is None:
                return None
            return OrderDetails(
                order_id=order.order_id,
                customer_email=order.customer.email,
                plan_slug=order.plan.slug,
                amount_cents=order.amount_cents,
                currency=order.currency,
                status=OrderStatus(order.status),
                created_at=order.created_at,
            )
