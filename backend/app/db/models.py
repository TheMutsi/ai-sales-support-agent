import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates
from sqlalchemy.sql import func

from app.core.origins import normalize_origin

EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    price_cents: Mapped[int]
    billing_period: Mapped[str]
    seat_limit: Mapped[int | None]
    api_call_limit: Mapped[int | None]
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="plan")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    api_key: Mapped[str] = mapped_column(unique=True, index=True)
    scope_overrides: Mapped[dict | None] = mapped_column(JSON)
    allowed_origins: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    support_hours: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @validates("allowed_origins")
    def _normalize_origins(self, _key: str, origins: list[str]) -> list[str]:
        normalized = []
        for origin in origins:
            clean = normalize_origin(origin)
            if clean is None:
                raise ValueError(f"not a plain origin (scheme://host[:port]): {origin!r}")
            if clean not in normalized:
                normalized.append(clean)
        return normalized

    secrets: Mapped[list["TenantSecret"]] = relationship(back_populates="tenant")


class TenantSmtp(Base):
    __tablename__ = "tenant_smtp"
    __table_args__ = (CheckConstraint("security in ('starttls', 'ssl', 'none')", name="ck_tenant_smtp_security"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    host: Mapped[str]
    port: Mapped[int]
    security: Mapped[str] = mapped_column(default="starttls")
    username: Mapped[str | None]
    password_encrypted: Mapped[str | None]
    from_address: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantSecret(Base):
    __tablename__ = "tenant_secrets"
    __table_args__ = (UniqueConstraint("tenant_id", "kid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    kid: Mapped[str]
    secret: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="secrets")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    identity_level: Mapped[str] = mapped_column(default="anonymous")
    linked_via: Mapped[str | None]
    customer_linked_at: Mapped[datetime | None]
    created_at: Mapped[datetime]
    last_activity_at: Mapped[datetime]
    last_seq: Mapped[int] = mapped_column(default=0, server_default="0")
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    handoff_status: Mapped[str] = mapped_column(default="none", server_default="none")
    pending_return_order_id: Mapped[str | None]
    pending_return_stage: Mapped[str | None]
    pending_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_agent_name: Mapped[str | None]
    handoff_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_reference: Mapped[str | None] = mapped_column(unique=True)
    escalation_route: Mapped[str | None]
    escalation_reason: Mapped[str | None]
    escalation_category: Mapped[str | None]
    escalation_status: Mapped[str | None]
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_resolved_by: Mapped[str | None]
    escalation_notes: Mapped[str | None] = mapped_column(Text)
    escalation_history: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    properties: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
        UniqueConstraint(
            "conversation_id", "client_message_id", name="uq_messages_conversation_client_id"
        ),
        UniqueConstraint("conversation_id", "reply_to_seq", name="uq_messages_conversation_reply"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    seq: Mapped[int]
    role: Mapped[str]
    author_name: Mapped[str | None]
    cards: Mapped[list | None] = mapped_column(JSON)
    kind: Mapped[str] = mapped_column(server_default="text", default="text")
    content: Mapped[str] = mapped_column(Text)
    client_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reply_to_seq: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(index=True)
    code_hash: Mapped[str]
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(default=0)
    consumed_at: Mapped[datetime | None]


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(index=True)
    email: Mapped[str | None]
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IdentificationEvent(Base):
    __tablename__ = "identification_events"
    __table_args__ = (Index("ix_identification_events_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL")
    )
    method: Mapped[str]
    outcome: Mapped[str]
    reason: Mapped[str | None]
    email_masked: Mapped[str | None]
    email_hmac: Mapped[str | None] = mapped_column(index=True)
    order_hmac: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class ReturnEvent(Base):
    __tablename__ = "return_events"
    __table_args__ = (
        Index("ix_return_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_return_events_conversation_order", "conversation_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    identity_level: Mapped[str]
    user_seq: Mapped[int]
    input_type: Mapped[str]
    action: Mapped[str | None]
    action_order_id: Mapped[str | None]
    reading: Mapped[str | None]
    stage_before: Mapped[str | None]
    stage_after: Mapped[str | None]
    outcome: Mapped[str]
    order_id: Mapped[str | None]
    order_status: Mapped[str | None]
    order_amount_cents: Mapped[int | None]
    candidates: Mapped[int]
    offer_refund_cents: Mapped[int | None]
    offer_credit_cents: Mapped[int | None]
    taken_refund_cents: Mapped[int | None]
    taken_credit_cents: Mapped[int | None]
    gift: Mapped[str | None]
    model: Mapped[str]
    app_version: Mapped[str]
    duration_ms: Mapped[int]


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)

    __table_args__ = (Index("ix_rate_limit_counters_window_start", "window_start"),)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_customers_tenant_external"),
        UniqueConstraint("tenant_id", "email", name="uq_customers_tenant_email"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    external_id: Mapped[str | None]
    email: Mapped[str] = mapped_column(index=True)
    company: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="trial")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(default="active")
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    current_period_end: Mapped[datetime]
    canceled_at: Mapped[datetime | None]

    customer: Mapped["Customer"] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = _uuid_pk()
    order_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    amount_cents: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    status: Mapped[str] = mapped_column(default="paid")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    item_name: Mapped[str | None]
    item_images: Mapped[list | None] = mapped_column(JSON)

    customer: Mapped["Customer"] = relationship()
    plan: Mapped["Plan"] = relationship()
    adjustment: Mapped["OrderAdjustment | None"] = relationship(uselist=False)


class OrderAdjustment(Base):
    __tablename__ = "order_adjustments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True)
    kind: Mapped[str]
    refund_cents: Mapped[int | None]
    credit_cents: Mapped[int | None]
    gift: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str]
    doc_type: Mapped[str]
    product_area: Mapped[str | None]
    plan_scope: Mapped[str | None]
    version: Mapped[str] = mapped_column(default="1.0")
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


class AgentPresence(Base):
    __tablename__ = "agent_presence"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    agent_name: Mapped[str] = mapped_column(primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_at: Mapped[datetime] = mapped_column(server_default=func.now())
    dataset_version: Mapped[str]
    llm_provider: Mapped[str]
    model: Mapped[str]
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
