"""A stand-in for the shop's orders API, backed by the `orders` table.

The call is async because the real one will be a network request; the query itself is
synchronous, so it runs in a worker thread instead of blocking the event loop.
"""

import asyncio
import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.business.returns import retention_offer
from app.db.models import Customer, Order, OrderAdjustment
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    RetentionChoice,
    RetentionReceipt,
    is_valid_order_id,
)


class SimulatedOrderSource:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def get_order(self, *, tenant_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        if not is_valid_order_id(order_id):
            return None
        return await asyncio.to_thread(self._read, tenant_id, order_id)

    async def list_orders(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, limit: int = 10
    ) -> list[OrderDetails]:
        return await asyncio.to_thread(self._list, tenant_id, customer_id, limit)

    def _list(self, tenant_id: uuid.UUID, customer_id: uuid.UUID, limit: int) -> list[OrderDetails]:
        with self._session_factory() as db:
            orders = (
                db.query(Order)
                .join(Customer, Order.customer_id == Customer.id)
                .options(joinedload(Order.customer), joinedload(Order.plan))
                .filter(Customer.tenant_id == tenant_id, Customer.id == customer_id)
                .order_by(Order.created_at.desc(), Order.order_id)
                .limit(limit)
                .all()
            )
            return [_details(order) for order in orders]

    async def cancel_order(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, order_id: str
    ) -> OrderDetails | None:
        if not is_valid_order_id(order_id):
            return None
        return await asyncio.to_thread(self._cancel, tenant_id, customer_id, order_id)

    def _cancel(self, tenant_id: uuid.UUID, customer_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        with self._session_factory() as db:
            order = self._owned_order(db, tenant_id, customer_id, order_id)
            if order is None or order.status != OrderStatus.OPEN:
                return None
            if db.query(OrderAdjustment).filter_by(order_id=order.id).first() is not None:
                return None  # kept with the offer: it is not cancelled any more
            order.status = OrderStatus.CANCELLED
            db.commit()
            return _details(order)

    async def keep_order_with_retention(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_id: str,
        choice: RetentionChoice,
    ) -> RetentionReceipt | None:
        if not is_valid_order_id(order_id):
            return None
        return await asyncio.to_thread(self._retain, tenant_id, customer_id, order_id, choice)

    def _retain(
        self, tenant_id: uuid.UUID, customer_id: uuid.UUID, order_id: str, choice: RetentionChoice
    ) -> RetentionReceipt | None:
        with self._session_factory() as db:
            order = self._owned_order(db, tenant_id, customer_id, order_id)
            if order is None or order.status not in (OrderStatus.OPEN, OrderStatus.IN_DELIVERY):
                return None
            offer = retention_offer(order.amount_cents)
            if offer is None:
                return None
            refund = choice is RetentionChoice.REFUND
            db.add(
                OrderAdjustment(
                    order_id=order.id,
                    kind="refund_to_card" if refund else "credits",
                    refund_cents=offer.refund_cents if refund else None,
                    credit_points=None if refund else offer.credit_points,
                )
            )
            try:
                db.commit()  # the unique order_id makes a second one fail, never double up
            except IntegrityError:
                db.rollback()
                return None
            return RetentionReceipt(
                order_id=order.order_id,
                choice=choice,
                refund_cents=offer.refund_cents if refund else None,
                credit_points=None if refund else offer.credit_points,
            )

    @staticmethod
    def _owned_order(db: Session, tenant_id, customer_id, order_id: str) -> Order | None:
        return (
            db.query(Order)
            .join(Customer, Order.customer_id == Customer.id)
            .options(joinedload(Order.customer), joinedload(Order.plan))
            .filter(
                Customer.tenant_id == tenant_id,
                Customer.id == customer_id,
                Order.order_id == order_id,
            )
            .with_for_update(of=Order)
            .one_or_none()
        )

    def _read(self, tenant_id: uuid.UUID, order_id: str) -> OrderDetails | None:
        with self._session_factory() as db:
            order = (
                db.query(Order)
                .join(Customer, Order.customer_id == Customer.id)
                .options(joinedload(Order.customer), joinedload(Order.plan))
                .filter(Customer.tenant_id == tenant_id, Order.order_id == order_id)
                .one_or_none()
            )
            return None if order is None else _details(order)


def _details(order: Order) -> OrderDetails:
    return OrderDetails(
        order_id=order.order_id,
        customer_email=order.customer.email,
        plan_slug=order.plan.slug,
        amount_cents=order.amount_cents,
        currency=order.currency,
        status=OrderStatus(order.status),
        created_at=order.created_at,
    )
