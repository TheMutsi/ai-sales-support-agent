import uuid
from datetime import UTC, datetime

from langchain_core.embeddings import Embeddings
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.embeddings import get_embeddings
from app.db.dev_tenant import ensure_dev_tenant
from app.db.models import Document, DocumentChunk, DocumentVersion
from app.db.session import SessionLocal
from app.rag.chunker import chunk_document
from app.rag.loaders import load_documents
from app.schemas.rag import DocType, SourceDocument

SEED_PUBLISHER = "seed"


class EmbeddingError(Exception):
    pass


def _embed(embedder: Embeddings, texts: list[str]) -> list[list[float]]:
    try:
        return embedder.embed_documents(texts)
    except Exception as exc:
        raise EmbeddingError("the embedding provider failed") from exc


def create_draft_version(db: Session, document: Document, content: str) -> DocumentVersion:
    latest = db.query(func.max(DocumentVersion.version)).filter_by(document_id=document.id).scalar() or 0
    draft = DocumentVersion(document_id=document.id, version=latest + 1, content=content, status="draft")
    db.add(draft)
    db.flush()
    return draft


def publish_version(
    db: Session, document_version_id: uuid.UUID, embedder: Embeddings, published_by: str
) -> int:
    version = db.get(DocumentVersion, document_version_id)
    if version is None:
        raise LookupError(f"document version {document_version_id} does not exist")
    document = version.document

    chunks = chunk_document(
        SourceDocument(
            title=document.title,
            when_to_use=document.when_to_use,
            doc_type=DocType(document.doc_type),
            product_area=document.product_area,
            plan_scope=document.plan_scope,
            version=document.version,
            source=document.source,
            content=version.content,
        )
    )
    vectors = _embed(embedder, [chunk.content for chunk in chunks])

    previous = db.get(DocumentVersion, document.published_version_id) if document.published_version_id else None
    if previous is not None and previous.id != version.id:
        archive_published_version(db, document)
    db.query(DocumentChunk).filter_by(document_version_id=version.id).delete()
    for chunk, vector in zip(chunks, vectors, strict=True):
        db.add(
            DocumentChunk(
                document_version_id=version.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=vector,
                chunk_metadata=chunk.metadata,
            )
        )
    version.status = "published"
    version.published_at = datetime.now(UTC)
    version.published_by = published_by
    document.published_version_id = version.id
    db.flush()
    return len(chunks)


def archive_published_version(db: Session, document: Document) -> None:
    published = db.get(DocumentVersion, document.published_version_id)
    published.status = "archived"
    document.published_version_id = None
    db.query(DocumentChunk).filter_by(document_version_id=published.id).delete()
    db.flush()


def ingest(session: Session, tenant_id: uuid.UUID, embedder: Embeddings | None = None) -> int:
    embedder = embedder or get_embeddings()
    source_documents = load_documents()
    chunks_written = 0
    for source in source_documents:
        chunks_written += _ingest_document(session, tenant_id, source, embedder)
        session.commit()
    _archive_sources_missing_from_disk(session, tenant_id, {source.source for source in source_documents})
    session.commit()
    return chunks_written


def _ingest_document(
    session: Session, tenant_id: uuid.UUID, source_document: SourceDocument, embedder: Embeddings
) -> int:
    document = session.query(Document).filter_by(tenant_id=tenant_id, source=source_document.source).one_or_none()
    if document is None:
        document = Document(tenant_id=tenant_id, source=source_document.source)
        session.add(document)
    document.title = source_document.title
    document.when_to_use = source_document.when_to_use
    document.doc_type = source_document.doc_type.value
    document.product_area = source_document.product_area
    document.plan_scope = source_document.plan_scope
    document.version = source_document.version
    document.origin = "seed"
    session.flush()

    published = session.get(DocumentVersion, document.published_version_id) if document.published_version_id else None
    if published is not None and published.content == source_document.content:
        return 0

    draft = create_draft_version(session, document, source_document.content)
    return publish_version(session, draft.id, embedder, SEED_PUBLISHER)


def _archive_sources_missing_from_disk(session: Session, tenant_id: uuid.UUID, sources: set[str]) -> None:
    serving = session.query(Document).filter(
        Document.tenant_id == tenant_id,
        Document.origin == "seed",
        Document.published_version_id.is_not(None),
        Document.source.not_in(sources),
    )
    for document in serving:
        archive_published_version(session, document)


if __name__ == "__main__":
    with SessionLocal() as db_session:
        dev_tenant = ensure_dev_tenant(db_session)
        if dev_tenant is None:
            raise SystemExit("the seed knowledge base loads only in local environments")
        db_session.commit()
        written = ingest(db_session, dev_tenant.id)
        print(f"Ingestion complete: {written} chunks written.")
