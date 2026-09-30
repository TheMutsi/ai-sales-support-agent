"""Agent-facing tool: search the KB, scoped to the asking customer's plan.

Wraps `app/rag/retriever.py` — the retrieval logic (embed the query,
cosine-similarity search, apply `doc_type`/`plan_scope` filters) already
lives there and isn't duplicated here. This module's only job is the two
things a lower-level retrieval function shouldn't know about: managing its
own DB session, and resolving `plan_scope` from the customer instead of
asking the LLM to supply a plan slug it might get wrong.

`min_score` is deliberately not applied here either, for the same reason
`retriever.search()` leaves it with no default: nobody has run the
evaluation suite (Stage 9) yet to pick a validated cutoff. Filtering on a
guessed number here would just move the fabricated threshold up one layer
instead of removing it.
"""

import uuid

from app.db.session import SessionLocal
from app.rag import retriever
from app.schemas.rag import DocType, RetrievedChunk
from app.tools._shared import current_subscription


def search_knowledge_base(
    customer_id: uuid.UUID, query: str, doc_type: DocType | None = None
) -> list[RetrievedChunk]:
    with SessionLocal() as session:
        # An unknown customer_id or a customer with no subscription yet still
        # gets a search — just unscoped by plan — rather than a hard failure:
        # answering a general product question shouldn't require a resolved
        # commercial relationship.
        subscription = current_subscription(session, customer_id)
        plan_scope = subscription.plan.slug if subscription is not None else None
        return retriever.search(session, query, doc_type=doc_type, plan_scope=plan_scope)
