import threading
import time
import uuid
from collections.abc import Callable

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Document, DocumentVersion
from app.db.session import SessionLocal
from app.rag.tokens import estimate_tokens
from app.schemas.rag import DocumentMapEntry


def load_published_document_map(tenant_id: uuid.UUID) -> tuple[DocumentMapEntry, ...]:
    with SessionLocal() as db:
        rows = db.execute(
            select(Document, DocumentVersion.content)
            .join(DocumentVersion, DocumentVersion.id == Document.published_version_id)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.id)
        ).all()
        return tuple(
            DocumentMapEntry(
                document_id=document.id,
                title=document.title,
                when_to_use=document.when_to_use,
                estimated_tokens=estimate_tokens(content),
                plan_scope=document.plan_scope,
            )
            for document, content in rows
        )


class DocumentCatalogCache:
    def __init__(
        self,
        loader: Callable[[uuid.UUID], tuple[DocumentMapEntry, ...]] = load_published_document_map,
        *,
        ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[uuid.UUID, tuple[float, tuple[DocumentMapEntry, ...]]] = {}

    def get(self, tenant_id: uuid.UUID) -> tuple[DocumentMapEntry, ...]:
        with self._lock:
            cached = self._entries.get(tenant_id)
            if cached is not None and self._clock() - cached[0] <= self._ttl:
                return cached[1]
            entries = self._loader(tenant_id)
            self._entries[tenant_id] = (self._clock(), entries)
            return entries

    def invalidate(self, tenant_id: uuid.UUID) -> None:
        with self._lock:
            self._entries.pop(tenant_id, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


document_catalog = DocumentCatalogCache(ttl_seconds=get_settings().tenant_config_ttl_seconds)


def get_document_map(tenant_id: uuid.UUID, plan_slug: str | None = None) -> tuple[DocumentMapEntry, ...]:
    entries = document_catalog.get(tenant_id)
    return tuple(entry for entry in entries if entry.plan_scope in (None, plan_slug))


def invalidate(tenant_id: uuid.UUID) -> None:
    document_catalog.invalidate(tenant_id)
