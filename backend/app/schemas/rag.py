import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class DocType(StrEnum):
    FEATURES = "features"
    BILLING = "billing"
    POLICY = "policy"
    FAQ = "faq"
    SECURITY = "security"
    INTEGRATIONS = "integrations"


class SourceDocument(BaseModel):
    title: str
    when_to_use: str
    doc_type: DocType
    product_area: str | None = None
    plan_scope: str | None = None
    version: str = "1.0"
    source: str
    content: str


class Chunk(BaseModel):
    content: str
    chunk_index: int
    metadata: dict = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    content: str
    score: float
    doc_type: DocType
    document_title: str
    source: str
    metadata: dict = Field(default_factory=dict)
    section: str | None = None
    version: int | None = None


class SourceReference(BaseModel):
    title: str
    doc_type: DocType
    source: str
    section: str | None = None
    version: int | None = None
