"""Integration tests for the DB schema and seed fixtures.

Require a real Postgres with the schema already migrated (`alembic upgrade head`)
against DATABASE_URL — pgvector's column type has no SQLite equivalent, so these
can't run against an in-memory database.
"""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Customer, Plan, Subscription
from app.db.seed import seed
from app.db.session import SessionLocal


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    session.query(Subscription).delete()
    session.query(Customer).delete()
    session.query(Plan).delete()
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_seed_creates_plans_customers_and_subscriptions(db: Session):
    seed(db)

    assert db.query(Plan).count() == 3
    assert db.query(Customer).count() == 6
    assert db.query(Subscription).count() == 6


def test_seed_links_customers_to_the_right_plan(db: Session):
    seed(db)

    enterprise_customer = db.query(Customer).filter_by(email="diego.ramirez@solvanmedia.com").one()
    [subscription] = enterprise_customer.subscriptions
    assert subscription.plan.slug == "enterprise"

    churned_customer = db.query(Customer).filter_by(email="tom.baxter@baxterandco.com").one()
    [subscription] = churned_customer.subscriptions
    assert subscription.status == "canceled"
    assert subscription.canceled_at is not None


def test_seed_is_idempotent(db: Session):
    seed(db)
    seed(db)

    assert db.query(Plan).count() == 3
    assert db.query(Customer).count() == 6
    assert db.query(Subscription).count() == 6
