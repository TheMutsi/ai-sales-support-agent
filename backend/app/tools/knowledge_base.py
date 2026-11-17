import uuid

from app.db.session import SessionLocal
from app.rag import retriever
from app.schemas.rag import DocType, RetrievedChunk
from app.tools._shared import current_subscription


def current_plan_slug(customer_id: uuid.UUID | None) -> str | None:
    if customer_id is None:
        return None
    with SessionLocal() as session:
        subscription = current_subscription(session, customer_id)
        return subscription.plan.slug if subscription is not None else None


def search_knowledge_base(
    query: str, doc_type: DocType | None = None, *, tenant_id: uuid.UUID, plan_slug: str | None
) -> list[RetrievedChunk]:
    with SessionLocal() as session:
        return retriever.search(session, query, tenant_id=tenant_id, doc_type=doc_type, plan_scope=plan_slug)
