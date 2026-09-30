"""Ingestion pipeline: loads KB docs, chunks them, embeds each chunk, and persists
`Document` + `DocumentChunk` rows.

Orchestration only — no chunking/embedding logic lives here, it delegates to
`loaders.load_documents()`, `chunker.chunk_document()`, and
`app.core.embeddings.get_embeddings()`. Run as a script
(`python -m app.rag.ingestion`) against a migrated DB, or re-run after KB content
changes to re-ingest.
"""

from sqlalchemy.orm import Session

from app.core.embeddings import get_embeddings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag.chunker import chunk_document
from app.rag.loaders import load_documents
from app.schemas.rag import SourceDocument


def ingest(session: Session) -> int:
    """Run the full pipeline: load -> chunk -> embed -> persist.

    Returns the number of `DocumentChunk` rows written. Commits once at the end,
    so a single failing document (a bad embedding call, say) leaves the KB at its
    previous state instead of half-updated.
    """
    chunks_written = sum(_ingest_document(session, source_document) for source_document in load_documents())
    session.commit()
    return chunks_written


def _ingest_document(session: Session, source_document: SourceDocument) -> int:
    _delete_existing(session, source_document.source)

    document = Document(
        title=source_document.title,
        doc_type=source_document.doc_type.value,
        product_area=source_document.product_area,
        plan_scope=source_document.plan_scope,
        version=source_document.version,
        source=source_document.source,
        content=source_document.content,
    )
    session.add(document)
    session.flush()  # assigns document.id, needed for the chunks' foreign key below

    chunks = chunk_document(source_document)
    vectors = get_embeddings().embed_documents([chunk.content for chunk in chunks])

    for chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=vector,
                chunk_metadata=chunk.metadata,
            )
        )

    return len(chunks)


def _delete_existing(session: Session, source: str) -> None:
    """Replace, don't duplicate: re-ingesting a KB file that was already loaded
    (matched on `Document.source`, the file's path relative to the KB root) removes
    its old `Document` first, so the retriever never sees a stale copy alongside
    the fresh one. Deleting just the `Document` is enough — `chunks` is a
    `cascade="all, delete-orphan"` relationship, backed by `ON DELETE CASCADE` at
    the DB level, so its `DocumentChunk` rows go with it."""
    existing = session.query(Document).filter_by(source=source).one_or_none()
    if existing is None:
        return

    session.delete(existing)
    session.flush()


if __name__ == "__main__":
    with SessionLocal() as db_session:
        written = ingest(db_session)
        print(f"Ingestion complete: {written} chunks written.")
