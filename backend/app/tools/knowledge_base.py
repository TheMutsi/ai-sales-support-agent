import uuid

from app.db.session import SessionLocal
from app.rag import retriever
from app.schemas.rag import DocType, RetrievedChunk
from app.tools._shared import current_subscription


def search_knowledge_base(
    customer_id: uuid.UUID | None, query: str, doc_type: DocType | None = None
) -> list[RetrievedChunk]:
    with SessionLocal() as session:
        subscription = current_subscription(session, customer_id) if customer_id else None
        plan_scope = subscription.plan.slug if subscription is not None else None
        return retriever.search(session, query, doc_type=doc_type, plan_scope=plan_scope)
