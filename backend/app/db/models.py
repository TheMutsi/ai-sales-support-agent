import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Plan(Base):
    """A subscription tier customers can be placed on (e.g. starter/pro/enterprise)."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    price_cents: Mapped[int]
    billing_period: Mapped[str]  # "monthly" | "annual"
    seat_limit: Mapped[int | None]
    api_call_limit: Mapped[int | None]
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="plan")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True, index=True)
    company: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="trial")  # trial | active | churned
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="customer")


class Subscription(Base):
    """A customer's commercial state over time, kept separate from `Customer` identity
    so plan changes, cancellations, and renewals have their own history."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(default="active")  # active | canceled | past_due
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    current_period_end: Mapped[datetime]
    canceled_at: Mapped[datetime | None]

    customer: Mapped["Customer"] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")


class Document(Base):
    """A knowledge-base source document. Content is populated by the RAG ingestion
    pipeline (Stage 3), not seeded here."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str]
    doc_type: Mapped[str]  # features | billing | policy | faq | security | integrations
    product_area: Mapped[str | None]
    plan_scope: Mapped[str | None]  # plan slug this doc applies to, null = all plans
    version: Mapped[str] = mapped_column(default="1.0")
    # Unique: the RAG ingestion pipeline (app/rag/ingestion.py) matches on this
    # to replace a document's rows on re-ingest instead of duplicating them —
    # the DB rejects a race between two ingestion runs instead of silently
    # allowing duplicate documents for the same source file.
    source: Mapped[str] = mapped_column(unique=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    chunk_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Ticket(Base):
    """A support ticket, created either by the agent (escalation, refund review)
    or, in the real product, by a human."""

    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    category: Mapped[str]  # escalation | refund | technical | billing | other
    subject: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="open")  # open | pending | resolved
    priority: Mapped[str] = mapped_column(default="medium")  # low | medium | high
    created_by: Mapped[str] = mapped_column(default="agent")  # agent | human
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None]

    customer: Mapped["Customer"] = relationship(back_populates="tickets")


class EvaluationRun(Base):
    """One execution of the evaluation suite (Stage 9) against the fixed dataset."""

    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_at: Mapped[datetime] = mapped_column(server_default=func.now())
    dataset_version: Mapped[str]
    llm_provider: Mapped[str]
    model: Mapped[str]
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
