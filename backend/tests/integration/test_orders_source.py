"""The simulated order source: what the shop's orders API will be, backed by a table.

Needs a migrated Postgres (see CLAUDE.md). The source is async and takes the tenant on every
call, so an order id from one shop can never be resolved for another.
"""

import asyncio
import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.models import Customer, Order, Plan, Subscription, Tenant, TenantSecret
from app.db.seed import seed
from app.db.session import SessionLocal
from app.orders.simulated import SimulatedOrderSource
from app.orders.source import OrderSource
from app.schemas.orders import OrderStatus


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
    assert db.query(Order).count() == 6
    seed(db)
    assert db.query(Order).count() == 6


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
