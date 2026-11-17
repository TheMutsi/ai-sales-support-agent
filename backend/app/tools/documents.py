import re
import uuid

from sqlalchemy import select

from app.db.models import Document, DocumentVersion
from app.db.session import SessionLocal
from app.rag.tokens import DOCUMENT_TOKEN_LIMIT, estimate_tokens
from app.schemas.rag import DocType, OpenDocumentsResult, OpenedDocument

CALL_TOKEN_LIMIT = 8000

_SECTION_HEADER_RE = re.compile(r"^## +(.+)$", re.MULTILINE)


def open_documents(
    tenant_id: uuid.UUID, plan_slug: str | None, document_ids: list[uuid.UUID]
) -> OpenDocumentsResult:
    requested = list(dict.fromkeys(document_ids))
    with SessionLocal() as db:
        rows = db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.id == Document.published_version_id)
            .where(Document.tenant_id == tenant_id, Document.id.in_(requested))
        ).all()
    found = {
        document.id: (document, version)
        for document, version in rows
        if document.plan_scope in (None, plan_slug)
    }

    result = OpenDocumentsResult()
    spent = 0
    for document_id in requested:
        if document_id not in found:
            result.not_found.append(document_id)
            continue
        document, version = found[document_id]
        tokens = estimate_tokens(version.content)
        opened = OpenedDocument(
            document_id=document.id,
            title=document.title,
            doc_type=DocType(document.doc_type),
            source=document.source,
            version=version.version,
            estimated_tokens=tokens,
        )
        if tokens > DOCUMENT_TOKEN_LIMIT:
            opened.omitted_reason = "document_too_long"
        elif spent + tokens > CALL_TOKEN_LIMIT:
            opened.omitted_reason = "call_limit_reached"
        else:
            opened.text = version.content
            spent += tokens
        if opened.text is None:
            opened.section_titles = [match.group(1).strip() for match in _SECTION_HEADER_RE.finditer(version.content)]
        result.documents.append(opened)
    return result
