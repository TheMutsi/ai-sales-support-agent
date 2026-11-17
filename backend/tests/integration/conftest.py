import pytest
from sqlalchemy.orm import Session

from app.core.tenant_config import tenant_configs
from app.db.models import (
    AgentPresence,
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
    ReturnEvent,
    SecurityEvent,
    Subscription,
    Tenant,
    TenantSecret,
    TenantSmtp,
)
from app.db.seed import seed as seed_fixtures
from app.db.session import SessionLocal


def _wipe(session: Session) -> None:
    session.query(DocumentChunk).delete()
    session.query(Document).delete()
    session.commit()


@pytest.fixture
def rag_db() -> Session:
    session = SessionLocal()
    _wipe(session)
    try:
        yield session
    finally:
        _wipe(session)
        session.close()


def _wipe_commercial_tables(session: Session) -> None:
    session.query(IdentificationEvent).delete()
    session.query(ReturnEvent).delete()
    session.query(RateLimitCounter).delete()
    session.query(AgentPresence).delete()
    session.query(Order).delete()
    session.query(Subscription).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.query(Customer).delete()
    session.query(OtpChallenge).delete()
    session.query(SecurityEvent).delete()
    session.query(TenantSecret).delete()
    session.query(TenantSmtp).delete()
    session.query(Tenant).delete()
    session.query(Plan).delete()
    session.commit()


@pytest.fixture(autouse=True)
def fresh_tenant_configs():
    tenant_configs.clear()
    yield
    tenant_configs.clear()


@pytest.fixture
def tenant_wipe() -> None:
    with SessionLocal() as session:
        _wipe_commercial_tables(session)
    yield
    with SessionLocal() as session:
        _wipe_commercial_tables(session)


@pytest.fixture
def seeded_db() -> Session:
    session = SessionLocal()
    _wipe_commercial_tables(session)
    seed_fixtures(session)
    try:
        yield session
    finally:
        _wipe_commercial_tables(session)
        session.close()


def customer_by_email(session: Session, email: str) -> Customer:
    return session.query(Customer).filter_by(email=email).one()
