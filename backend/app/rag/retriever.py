"""Retrieval: embeds a query and returns the top-k most similar chunks from
`document_chunks`, using pgvector's cosine-distance similarity search.

This is the exact contract `app/tools/knowledge_base.py` calls — keep the
signature stable once it's in use elsewhere, since changing it later means
touching that caller too.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.embeddings import get_embeddings
from app.db.models import Document, DocumentChunk
from app.schemas.rag import DocType, RetrievedChunk


def search(
    session: Session,
    query: str,
    top_k: int = 5,
    doc_type: DocType | None = None,
    plan_scope: str | None = None,
    min_score: float | None = None,
) -> list[RetrievedChunk]:
    """Embed `query` and return the `top_k` most similar chunks.

    `doc_type`/`plan_scope` are optional pre-filters applied before the similarity
    search (e.g. the agent already knows it's a refund question, so only search
    `policy` docs) — this narrows the search space and avoids retrieving an
    off-topic-but-vector-close chunk that happens to share vocabulary with the
    query. A `plan_scope` filter matches that plan's docs *and* docs with no plan
    scope (`plan_scope IS NULL`, meaning "applies to every plan") — an exact-match
    filter would hide something like the general Terms & Conditions from every
    plan-specific query, which is wrong: those apply to everyone regardless of
    plan.

    Cosine similarity search always returns the `top_k` *closest* chunks, even for
    an off-topic or garbled query where none of them are a good match — there's no
    built-in "found nothing relevant" case. `min_score` is an escape hatch for
    that: pass it to drop chunks below that similarity score instead of returning
    a false-confident answer. There's no default cutoff here — the right value is
    an empirical question for the evaluation suite (Stage 9) to answer, not a
    number to guess at in this module.
    """
    query_vector = get_embeddings().embed_query(query)
    distance = DocumentChunk.embedding.cosine_distance(query_vector)

    # Select specific columns, not the full DocumentChunk/Document entities:
    # RetrievedChunk never reads the 768-dim embedding vector or a document's
    # full markdown content, and a top-k result commonly has several chunks
    # from the same document — fetching whole entities would transfer that
    # vector and re-transfer that content once per matching chunk for nothing.
    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.chunk_metadata,
            Document.id,
            Document.doc_type,
            distance,
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .order_by(distance)
        .limit(top_k)
    )

    if doc_type is not None:
        statement = statement.where(Document.doc_type == doc_type.value)
    if plan_scope is not None:
        statement = statement.where((Document.plan_scope == plan_scope) | Document.plan_scope.is_(None))

    rows = session.execute(statement).all()

    results = [
        RetrievedChunk(
            chunk_id=chunk_id,
            content=content,
            metadata=chunk_metadata,
            document_id=document_id,
            doc_type=DocType(doc_type_value),
            score=1 - distance_value,
        )
        for chunk_id, content, chunk_metadata, document_id, doc_type_value, distance_value in rows
    ]

    if min_score is not None:
        results = [result for result in results if result.score >= min_score]

    return results
