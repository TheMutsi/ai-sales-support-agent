"""Shared fixtures for integration tests that need a real Postgres session."""

import pytest
from sqlalchemy.orm import Session

from app.core.tenant_config import tenant_configs
from app.db.models import (
    Conversation,
    Customer,
    Document,
    DocumentChunk,
    IdentificationEvent,
    Message,
    Order,
    OtpChallenge,
    Plan,
    RateLimitCounter,
    SecurityEvent,
    Subscription,
    Tenant,
    TenantSecret,
    Ticket,
)
from app.db.seed import seed as seed_fixtures
from app.db.session import SessionLocal


def _wipe(session: Session) -> None:
    session.query(DocumentChunk).delete()
    session.query(Document).delete()
    session.commit()


@pytest.fixture
def rag_db() -> Session:
    """Used by `test_rag_ingestion.py` and `test_retriever.py` — both need
    `Document`/`DocumentChunk` wiped before and after each test."""
    session = SessionLocal()
    _wipe(session)
    try:
        yield session
    finally:
        # The functions under test (ingest(), _add_document() helpers) commit
        # internally, so a plain rollback() here wouldn't undo anything — clean
        # up explicitly instead of leaving synthetic test rows in what's
        # otherwise the developer's real KB data.
        _wipe(session)
        session.close()


def _wipe_commercial_tables(session: Session) -> None:
    session.query(IdentificationEvent).delete()
    session.query(RateLimitCounter).delete()
    session.query(Ticket).delete()
    session.query(Order).delete()
    session.query(Subscription).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.query(Customer).delete()
    session.query(OtpChallenge).delete()
    session.query(SecurityEvent).delete()
    session.query(TenantSecret).delete()
    session.query(Tenant).delete()
    session.query(Plan).delete()
    session.commit()


@pytest.fixture(autouse=True)
def fresh_tenant_configs():
    """The tenants' configuration is cached; every test builds its own tenants, so none may see a
    snapshot a previous one loaded."""
    tenant_configs.clear()
    yield
    tenant_configs.clear()


@pytest.fixture
def tenant_wipe() -> None:
    """Clears tenants and the customers that hang off them before and after a
    test; the test builds its own tenant (see `test_api_auth_login.py`)."""
    with SessionLocal() as session:
        _wipe_commercial_tables(session)
    yield
    with SessionLocal() as session:
        _wipe_commercial_tables(session)


@pytest.fixture
def seeded_db() -> Session:
    """Used by `tests/integration/test_tools_*.py` (excluding
    `test_tools_knowledge_base.py`'s own `rag_db` needs). Loads real
    plans/customers/subscriptions from `data/seed/` so those tests assert
    against known rows (by slug/email) instead of fabricating throwaway ones —
    same approach as `test_db_seed.py`, but seeded automatically since these
    tests exercise the tools layer, not the seeding process itself."""
    session = SessionLocal()
    _wipe_commercial_tables(session)
    seed_fixtures(session)
    try:
        yield session
    finally:
        _wipe_commercial_tables(session)
        session.close()


def customer_by_email(session: Session, email: str) -> Customer:
    """Looks up a `seeded_db` customer by their `data/seed/customers.json`
    email — the tools-layer tests key off email (a stable, readable fixture
    identifier) instead of a UUID, same as `test_db_seed.py` does."""
    return session.query(Customer).filter_by(email=email).one()
