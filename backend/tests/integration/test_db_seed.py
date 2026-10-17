"""Integration tests for the DB schema and seed fixtures.

Require a real Postgres with the schema already migrated (`alembic upgrade head`)
against DATABASE_URL — pgvector's column type has no SQLite equivalent, so these
can't run against an in-memory database.
"""

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Customer, Plan, Subscription, Tenant, TenantSecret
from app.db.seed import DEV_TENANT_API_KEY, DEV_TENANT_KID, DEV_TENANT_SECRET, seed
from app.db.session import SessionLocal


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    session.query(Subscription).delete()
    session.query(Customer).delete()
    session.query(TenantSecret).delete()
    session.query(Tenant).delete()
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


def test_seed_creates_a_dev_tenant_with_a_secret_and_links_every_customer(db: Session):
    seed(db)

    tenant = db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one()
    assert [(s.kid, s.active) for s in tenant.secrets] == [(DEV_TENANT_KID, True)]
    customers = db.query(Customer).all()
    assert customers and all(c.tenant_id == tenant.id for c in customers)
    # The shop's id for a seeded customer is their email, so a dev token's `sub` is readable.
    assert all(c.external_id == c.email for c in customers)


def test_seed_backfills_customers_that_predate_the_dev_tenant(db: Session):
    seed(db)
    db.query(Customer).update({"tenant_id": None, "external_id": None})
    db.commit()

    seed(db)

    assert db.query(Customer).filter(Customer.tenant_id.is_(None)).count() == 0
    assert db.query(Tenant).count() == 1


def test_seed_skips_the_dev_tenant_outside_local_environments(db: Session, monkeypatch):
    """A well-known secret must never be written to a real deployment's database."""
    from app.db import seed as seed_module

    production = Settings(app_env="production", session_signing_key="p" * 32)
    monkeypatch.setattr(seed_module, "get_settings", lambda: production)

    seed(db)

    assert db.query(Tenant).count() == 0


def test_seed_does_not_touch_another_tenants_customer_with_the_same_email(db: Session):
    other = Tenant(name="Other shop", api_key="pk_other")
    db.add(other)
    db.flush()
    db.add(Customer(name="Ava", email="ava.chen@northlightstudio.com", tenant_id=other.id))
    db.commit()

    seed(db)

    dev = db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one()
    ava = db.query(Customer).filter_by(email="ava.chen@northlightstudio.com")
    assert {c.tenant_id for c in ava} == {other.id, dev.id}


def test_seed_restores_a_dev_secret_that_was_deactivated(db: Session):
    seed(db)
    db.query(TenantSecret).update({"active": False, "secret": "stale"})
    db.commit()

    seed(db)

    secret = db.query(TenantSecret).one()
    assert secret.active and secret.secret == DEV_TENANT_SECRET
