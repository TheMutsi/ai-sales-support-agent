from sqlalchemy.orm import Session

from app.core.embeddings import get_embeddings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.rag.chunker import chunk_document
from app.rag.loaders import load_documents
from app.schemas.rag import SourceDocument


def ingest(session: Session) -> int:
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
    session.flush()

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
    existing = session.query(Document).filter_by(source=source).one_or_none()
    if existing is None:
        return

    session.delete(existing)
    session.flush()


if __name__ == "__main__":
    with SessionLocal() as db_session:
        written = ingest(db_session)
        print(f"Ingestion complete: {written} chunks written.")
