import pytest
from sqlalchemy.orm import Session

from app.core.tenant_config import tenant_configs
from app.db.models import (
    AgentPresence,
    Conversation,
    Customer,
    Document,
    DocumentChunk,
    DocumentVersion,
    IdentificationEvent,
    ItemOffer,
    ItemTag,
    Message,
    Order,
    OtpChallenge,
    Plan,
    RateLimitCounter,
    RecommendationItem,
    RecommendationTag,
    RecommendationType,
    ReturnEvent,
    SecurityEvent,
    Subscription,
    Tenant,
    TenantSecret,
    TenantSmtp,
)
from app.db.seed import seed as seed_fixtures
from app.db.session import SessionLocal

KB_TEST_TENANT_API_KEY = "pk_kb_test"


def kb_test_tenant(session: Session) -> Tenant:
    tenant = session.query(Tenant).filter_by(api_key=KB_TEST_TENANT_API_KEY).one_or_none()
    if tenant is None:
        tenant = Tenant(name="Knowledge base test shop", api_key=KB_TEST_TENANT_API_KEY)
        session.add(tenant)
        session.commit()
    return tenant


def add_published_document(
    session: Session,
    *,
    source: str,
    chunks: list[tuple[str, list[float]]],
    tenant: Tenant | None = None,
    doc_type: str = "faq",
    plan_scope: str | None = None,
    title: str | None = None,
    section_titles: list[str | None] | None = None,
    content: str = "x",
) -> Document:
    tenant = tenant or kb_test_tenant(session)
    document = Document(
        tenant_id=tenant.id, title=title or source, when_to_use="test", doc_type=doc_type, source=source,
        plan_scope=plan_scope,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(document_id=document.id, version=1, content=content, status="published")
    session.add(version)
    session.flush()
    for index, (chunk_content, embedding) in enumerate(chunks):
        section_title = section_titles[index] if section_titles else None
        session.add(
            DocumentChunk(
                document_version_id=version.id, chunk_index=index, content=chunk_content, embedding=embedding,
                chunk_metadata={"section_title": section_title} if section_title else {},
            )
        )
    document.published_version_id = version.id
    session.commit()
    return document


def _wipe_knowledge_base(session: Session) -> None:
    session.query(DocumentChunk).delete()
    session.query(DocumentVersion).delete()
    session.query(Document).delete()


def wipe_recommendation_catalog(session: Session) -> None:
    session.query(ItemTag).delete()
    session.query(ItemOffer).delete()
    session.query(RecommendationItem).delete()
    session.query(RecommendationTag).delete()
    session.query(RecommendationType).delete()


def _wipe(session: Session) -> None:
    _wipe_knowledge_base(session)
    session.query(Tenant).filter_by(api_key=KB_TEST_TENANT_API_KEY).delete()
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
    _wipe_knowledge_base(session)
    wipe_recommendation_catalog(session)
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
