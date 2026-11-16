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
    query_vector = get_embeddings().embed_query(query)
    distance = DocumentChunk.embedding.cosine_distance(query_vector)

    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.chunk_metadata,
            Document.id,
            Document.doc_type,
            Document.title,
            Document.source,
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
            document_title=title,
            source=source,
            score=1 - distance_value,
        )
        for (
            chunk_id,
            content,
            chunk_metadata,
            document_id,
            doc_type_value,
            title,
            source,
            distance_value,
        ) in rows
    ]

    if min_score is not None:
        results = [result for result in results if result.score >= min_score]

    return results
