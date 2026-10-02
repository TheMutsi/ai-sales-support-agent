"""Typed contracts for the RAG pipeline.

Every module in `app/rag/` communicates through these types instead of raw
dicts/strings, per Core Principle #2 (explicit, strongly-typed state) and #3
(strongly-typed tool inputs/outputs). This also freezes the shape `retriever.py`
hands to `app/tools/knowledge_base.py`, and from there to the agent graph
(`app/agent/`), so it can be built against a stable contract.
"""

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class DocType(StrEnum):
    """KB categories for unstructured content retrieved by similarity search.
    Exact prices and plan limits are structured facts served from the `plans`
    table via a tool in `app/tools/`, so they have no entry here."""

    FEATURES = "features"
    BILLING = "billing"
    POLICY = "policy"
    FAQ = "faq"
    SECURITY = "security"
    INTEGRATIONS = "integrations"


class SourceDocument(BaseModel):
    """One KB source file, as returned by a loader — before chunking."""

    title: str
    doc_type: DocType
    product_area: str | None = None
    plan_scope: str | None = None  # plan slug this doc applies to; None = all plans
    version: str = "1.0"
    source: str  # relative path of the markdown file, used as the dedup key on re-ingest
    content: str  # raw markdown body, front-matter stripped


class Chunk(BaseModel):
    """One chunk of a `SourceDocument`, produced by a chunking strategy — before
    embedding or persistence."""

    content: str
    chunk_index: int
    metadata: dict = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    """One result from `retriever.search()`: a persisted, embedded chunk plus its
    similarity score against the query."""

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    content: str
    score: float
    doc_type: DocType
    metadata: dict = Field(default_factory=dict)
