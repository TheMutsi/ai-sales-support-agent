import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from langchain_core.embeddings import Embeddings
from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.permissions import Permission
from app.admin.session import AdminSession
from app.api.admin_deps import error, require_tenant_permission
from app.core.embeddings import get_embeddings
from app.db.models import Document, DocumentVersion, Plan
from app.db.session import get_db
from app.rag import catalog
from app.rag.ingestion import (
    EmbeddingError,
    archive_published_version,
    create_draft_version,
    publish_version,
)
from app.rag.tokens import DOCUMENT_TOKEN_LIMIT, estimate_tokens
from app.schemas.rag import DocType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

_READ = require_tenant_permission(Permission.KB_READ)
_WRITE = require_tenant_permission(Permission.KB_WRITE)


def get_embedder() -> Embeddings:
    return get_embeddings()


class VersionView(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    created_at: datetime
    published_at: datetime | None
    published_by: str | None
    estimated_tokens: int
    fits_whole_document: bool


class VersionDetail(VersionView):
    content: str


class DocumentItem(BaseModel):
    id: uuid.UUID
    title: str
    doc_type: str
    plan_scope: str | None
    when_to_use: str
    published_version_id: uuid.UUID | None
    published_version: int | None
    has_draft: bool
    estimated_tokens: int
    fits_whole_document: bool


class DocumentDetail(DocumentItem):
    product_area: str | None
    versions: list[VersionDetail]


def _refuse_line_breaks(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("must be a single line")
    return value


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


WhenToUse = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    AfterValidator(_refuse_line_breaks),
]
Title = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_refuse_line_breaks)]
PlanScope = Annotated[str | None, Field(max_length=100), AfterValidator(_blank_to_none)]


class NewDocumentRequest(BaseModel):
    title: Title
    doc_type: DocType
    plan_scope: PlanScope
    product_area: str | None = Field(default=None, max_length=100)
    when_to_use: WhenToUse
    content: str = Field(max_length=200_000)


class DocumentDetailsRequest(BaseModel):
    title: Title
    doc_type: DocType
    plan_scope: PlanScope
    when_to_use: WhenToUse


class DraftRequest(BaseModel):
    content: str = Field(max_length=200_000)


def _version_view(version: DocumentVersion) -> dict:
    tokens = estimate_tokens(version.content)
    return {
        "id": version.id,
        "version": version.version,
        "status": version.status,
        "created_at": version.created_at,
        "published_at": version.published_at,
        "published_by": version.published_by,
        "estimated_tokens": tokens,
        "fits_whole_document": tokens <= DOCUMENT_TOKEN_LIMIT,
    }


def _versions_by_id(document: Document) -> dict[uuid.UUID, DocumentVersion]:
    return {version.id: version for version in document.versions}


def _draft_of(document: Document) -> DocumentVersion | None:
    return next((version for version in document.versions if version.status == "draft"), None)


def _item(document: Document) -> DocumentItem:
    published = _versions_by_id(document).get(document.published_version_id)
    draft = _draft_of(document)
    shown = published or draft
    tokens = estimate_tokens(shown.content) if shown else 0
    return DocumentItem(
        id=document.id,
        title=document.title,
        doc_type=document.doc_type,
        plan_scope=document.plan_scope,
        when_to_use=document.when_to_use,
        published_version_id=document.published_version_id,
        published_version=published.version if published else None,
        has_draft=draft is not None,
        estimated_tokens=tokens,
        fits_whole_document=tokens <= DOCUMENT_TOKEN_LIMIT,
    )


def _detail(document: Document) -> DocumentDetail:
    versions = sorted(document.versions, key=lambda version: version.version, reverse=True)
    return DocumentDetail(
        **_item(document).model_dump(),
        product_area=document.product_area,
        versions=[VersionDetail(**_version_view(version), content=version.content) for version in versions],
    )


def _document_of(db: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise error(404, "document_not_found")
    return document


def _known_plan_scope(db: Session, plan_scope: str | None) -> str | None:
    if plan_scope is not None and db.scalar(select(Plan.id).where(Plan.slug == plan_scope)) is None:
        raise error(422, "unknown_plan")
    return plan_scope


def _publish(db: Session, version_id: uuid.UUID, embedder: Embeddings, published_by: str) -> None:
    try:
        publish_version(db, version_id, embedder, published_by)
        db.commit()
    except LookupError:
        db.rollback()
        raise error(404, "version_not_found") from None
    except EmbeddingError:
        logger.exception("embedding failed while publishing version %s", version_id)
        db.rollback()
        raise error(502, "embedding_failed") from None


@router.get("/tenants/{tenant_id}/kb/documents", response_model=list[DocumentItem])
def list_documents(
    tenant_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_READ)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DocumentItem]:
    documents = db.scalars(select(Document).where(Document.tenant_id == tenant_id).order_by(Document.title))
    return [_item(document) for document in documents]


@router.get("/tenants/{tenant_id}/kb/documents/{document_id}", response_model=DocumentDetail)
def read_document(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_READ)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    return _detail(_document_of(db, tenant_id, document_id))


@router.post("/tenants/{tenant_id}/kb/documents", response_model=DocumentDetail, status_code=201)
def create_document(
    tenant_id: uuid.UUID,
    body: NewDocumentRequest,
    session: Annotated[AdminSession, Depends(_WRITE)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = Document(
        tenant_id=tenant_id,
        title=body.title,
        doc_type=body.doc_type.value,
        plan_scope=_known_plan_scope(db, body.plan_scope),
        product_area=body.product_area,
        when_to_use=body.when_to_use,
        source=f"admin/{uuid.uuid4()}",
    )
    db.add(document)
    db.flush()
    create_draft_version(db, document, body.content)
    db.commit()
    db.refresh(document)
    return _detail(document)


@router.patch("/tenants/{tenant_id}/kb/documents/{document_id}", response_model=DocumentDetail)
def update_document_details(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentDetailsRequest,
    session: Annotated[AdminSession, Depends(_WRITE)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = _document_of(db, tenant_id, document_id)
    document.title = body.title
    document.doc_type = body.doc_type.value
    document.plan_scope = _known_plan_scope(db, body.plan_scope)
    document.when_to_use = body.when_to_use
    db.commit()
    catalog.invalidate(tenant_id)
    db.refresh(document)
    return _detail(document)


@router.put("/tenants/{tenant_id}/kb/documents/{document_id}/draft", response_model=DocumentDetail)
def save_draft(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DraftRequest,
    session: Annotated[AdminSession, Depends(_WRITE)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = _document_of(db, tenant_id, document_id)
    draft = _draft_of(document)
    if draft is None:
        create_draft_version(db, document, body.content)
    else:
        draft.content = body.content
    db.commit()
    db.refresh(document)
    return _detail(document)


@router.post("/tenants/{tenant_id}/kb/documents/{document_id}/draft/publish", response_model=DocumentDetail)
def publish_draft(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_WRITE)],
    db: Annotated[Session, Depends(get_db)],
    embedder: Annotated[Embeddings, Depends(get_embedder)],
) -> DocumentDetail:
    document = _document_of(db, tenant_id, document_id)
    draft = _draft_of(document)
    if draft is None:
        raise error(404, "no_draft")
    _publish(db, draft.id, embedder, session.name)
    catalog.invalidate(tenant_id)
    db.refresh(document)
    return _detail(document)


@router.post(
    "/tenants/{tenant_id}/kb/documents/{document_id}/versions/{version_id}/publish",
    response_model=DocumentDetail,
)
def republish_version(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_WRITE)],
    db: Annotated[Session, Depends(get_db)],
    embedder: Annotated[Embeddings, Depends(get_embedder)],
) -> DocumentDetail:
    document = _document_of(db, tenant_id, document_id)
    version = _versions_by_id(document).get(version_id)
    if version is None:
        raise error(404, "version_not_found")
    if version.status != "archived":
        raise error(409, "version_not_archived")
    _publish(db, version.id, embedder, session.name)
    catalog.invalidate(tenant_id)
    db.refresh(document)
    return _detail(document)


@router.post("/tenants/{tenant_id}/kb/documents/{document_id}/archive", response_model=DocumentDetail)
def archive_document(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_WRITE)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetail:
    document = _document_of(db, tenant_id, document_id)
    if document.published_version_id is not None:
        archive_published_version(db, document)
    db.commit()
    catalog.invalidate(tenant_id)
    db.refresh(document)
    return _detail(document)
