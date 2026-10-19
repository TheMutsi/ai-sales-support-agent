"""The simulated order source: what the shop's orders API will be, backed by a table.

Needs a migrated Postgres (see CLAUDE.md). The source is async and takes the tenant on every
call, so an order id from one shop can never be resolved for another.
"""

import asyncio
import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.models import Customer, Order, OrderAdjustment, Plan, Subscription, Tenant, TenantSecret
from app.db.seed import seed
from app.db.session import SessionLocal
from app.orders.simulated import SimulatedOrderSource
from app.orders.source import OrderSource
from app.schemas.orders import OrderStatus, RetentionChoice


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    for model in (Order, Subscription, Customer, TenantSecret, Tenant, Plan):
        session.query(model).delete()
    session.commit()
    seed(session)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _first_order(db: Session) -> Order:
    return db.query(Order).join(Customer).filter(Customer.email.like("ava.chen@%")).one()


def test_the_simulated_source_satisfies_the_interface():
    assert isinstance(SimulatedOrderSource(SessionLocal), OrderSource)


def test_seed_gives_every_customer_one_order_and_is_idempotent(db: Session):
    assert db.query(Order).count() == 10  # the six customers' and the four demo shop ones
    seed(db)
    assert db.query(Order).count() == 10


def test_finds_an_order_for_its_tenant_with_the_customer_and_plan(db: Session):
    order = _first_order(db)
    tenant_id = order.customer.tenant_id
    found = asyncio.run(
        SimulatedOrderSource(SessionLocal).get_order(tenant_id=tenant_id, order_id=order.order_id)
    )
    assert found is not None
    assert found.order_id == order.order_id
    assert found.customer_email == "ava.chen@northlightstudio.com"
    assert found.plan_slug == "starter"
    assert found.amount_cents == 2900
    assert found.status is OrderStatus.PAID


def test_an_order_is_invisible_to_another_tenant(db: Session):
    order = _first_order(db)
    found = asyncio.run(
        SimulatedOrderSource(SessionLocal).get_order(tenant_id=uuid.uuid4(), order_id=order.order_id)
    )
    assert found is None


def test_unknown_and_malformed_ids_are_none_not_errors(db: Session):
    tenant_id = _first_order(db).customer.tenant_id
    source = SimulatedOrderSource(SessionLocal)
    for order_id in ("z" * 20, "short", "x'; DROP TABLE orders;--"):
        assert asyncio.run(source.get_order(tenant_id=tenant_id, order_id=order_id)) is None


def test_statuses_follow_the_customer_s_situation(db: Session):
    by_email = {o.customer.email: o.status for o in db.query(Order)}
    assert by_email["helena.ostrowski@ridgeportlegal.com"] == "pending"  # past_due
    assert by_email["tom.baxter@baxterandco.com"] == "refunded"  # canceled
    assert by_email["priya.anand@bluecrestlogistics.com"] == "paid"


def test_a_customers_orders_are_listed_for_that_customer_only(db: Session):
    mail3 = db.query(Customer).filter_by(email="mail3@gmail.com").one()
    source = SimulatedOrderSource(SessionLocal)

    orders = asyncio.run(source.list_orders(tenant_id=mail3.tenant_id, customer_id=mail3.id))
    others = asyncio.run(
        source.list_orders(
            tenant_id=mail3.tenant_id,
            customer_id=db.query(Customer).filter_by(email="mail4@gmail.com").one().id,
        )
    )
    assert [o.customer_email for o in others] == ["mail4@gmail.com"]

    assert [(o.customer_email, o.status, o.amount_cents) for o in orders] == [
        ("mail3@gmail.com", OrderStatus.IN_DELIVERY, 6999)
    ]


def test_another_tenants_id_lists_nothing_for_a_customer(db: Session):
    mail1 = db.query(Customer).filter_by(email="mail1@gmail.com").one()

    orders = asyncio.run(
        SimulatedOrderSource(SessionLocal).list_orders(tenant_id=uuid.uuid4(), customer_id=mail1.id)
    )

    assert orders == []


def _customer_and_order(db: Session, email: str):
    customer = db.query(Customer).filter_by(email=email).one()
    order = db.query(Order).filter_by(customer_id=customer.id).one()
    return customer, order


def test_an_open_order_is_cancelled_once_and_an_order_in_delivery_cannot_be(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    open_customer, open_order = _customer_and_order(db, "mail1@gmail.com")
    delivery_customer, delivery_order = _customer_and_order(db, "mail3@gmail.com")

    cancelled = asyncio.run(
        source.cancel_order(
            tenant_id=open_customer.tenant_id, customer_id=open_customer.id, order_id=open_order.order_id
        )
    )
    again = asyncio.run(
        source.cancel_order(
            tenant_id=open_customer.tenant_id, customer_id=open_customer.id, order_id=open_order.order_id
        )
    )
    shipped = asyncio.run(
        source.cancel_order(
            tenant_id=delivery_customer.tenant_id,
            customer_id=delivery_customer.id,
            order_id=delivery_order.order_id,
        )
    )

    assert cancelled is not None and cancelled.status is OrderStatus.CANCELLED
    assert again is None and shipped is None
    db.expire_all()
    assert delivery_order.status == "in_delivery"


def test_nobody_cancels_or_keeps_an_order_that_is_not_theirs(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    owner, order = _customer_and_order(db, "mail1@gmail.com")
    stranger = db.query(Customer).filter_by(email="mail2@gmail.com").one()

    cancelled = asyncio.run(
        source.cancel_order(tenant_id=owner.tenant_id, customer_id=stranger.id, order_id=order.order_id)
    )
    kept = asyncio.run(
        source.keep_order_with_retention(
            tenant_id=owner.tenant_id, customer_id=stranger.id, order_id=order.order_id,
            choice=RetentionChoice.REFUND,
        )
    )

    assert cancelled is None and kept is None
    db.expire_all()
    assert order.status == "open"


def test_keeping_an_order_with_the_offer_is_recorded_once_per_order(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    customer, order = _customer_and_order(db, "mail2@gmail.com")

    def keep(choice):
        return asyncio.run(
            source.keep_order_with_retention(
                tenant_id=customer.tenant_id, customer_id=customer.id, order_id=order.order_id,
                choice=choice,
            )
        )

    first = keep(RetentionChoice.CREDITS)
    second = keep(RetentionChoice.REFUND)  # a second one must not stack

    assert first is not None and (first.credit_points, first.refund_cents) == (2100, None)
    assert second is None
    db.expire_all()
    [adjustment] = db.query(OrderAdjustment).filter_by(order_id=order.id).all()
    assert (adjustment.kind, adjustment.credit_points) == ("credits", 2100)
    assert order.status == "open"  # kept: nothing is cancelled


def test_a_cancelled_order_cannot_be_kept_with_an_offer(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    customer, order = _customer_and_order(db, "mail1@gmail.com")
    asyncio.run(source.cancel_order(tenant_id=customer.tenant_id, customer_id=customer.id, order_id=order.order_id))

    kept = asyncio.run(
        source.keep_order_with_retention(
            tenant_id=customer.tenant_id, customer_id=customer.id, order_id=order.order_id,
            choice=RetentionChoice.REFUND,
        )
    )

    assert kept is None


def test_an_order_kept_with_the_offer_cannot_be_cancelled_afterwards(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    customer, order = _customer_and_order(db, "mail2@gmail.com")
    ids = {"tenant_id": customer.tenant_id, "customer_id": customer.id, "order_id": order.order_id}

    kept = asyncio.run(source.keep_order_with_retention(**ids, choice=RetentionChoice.REFUND))
    cancelled = asyncio.run(source.cancel_order(**ids))

    assert kept is not None and (kept.refund_cents, kept.credit_points) == (1400, None)
    assert cancelled is None
    db.expire_all()
    assert order.status == "open"


def test_an_order_below_the_threshold_cannot_be_kept_with_an_offer(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    customer, order = _customer_and_order(db, "mail1@gmail.com")  # $29.99

    kept = asyncio.run(
        source.keep_order_with_retention(
            tenant_id=customer.tenant_id, customer_id=customer.id, order_id=order.order_id,
            choice=RetentionChoice.CREDITS,
        )
    )

    assert kept is None
    assert db.query(OrderAdjustment).count() == 0


def test_another_tenants_id_cannot_cancel_or_keep_an_order(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    customer, order = _customer_and_order(db, "mail2@gmail.com")
    ids = {"tenant_id": uuid.uuid4(), "customer_id": customer.id, "order_id": order.order_id}

    assert asyncio.run(source.cancel_order(**ids)) is None
    assert asyncio.run(source.keep_order_with_retention(**ids, choice=RetentionChoice.REFUND)) is None


def test_an_order_kept_with_the_offer_says_so_when_read_again(db: Session):
    source = SimulatedOrderSource(SessionLocal)
    customer, order = _customer_and_order(db, "mail2@gmail.com")
    ids = {"tenant_id": customer.tenant_id, "customer_id": customer.id}
    asyncio.run(
        source.keep_order_with_retention(order_id=order.order_id, choice=RetentionChoice.CREDITS, **ids)
    )

    [read] = asyncio.run(source.list_orders(**ids))

    assert read.status is OrderStatus.OPEN
    assert read.retention is not None and (read.retention.choice, read.retention.credit_points) == (
        RetentionChoice.CREDITS,
        2100,
    )
