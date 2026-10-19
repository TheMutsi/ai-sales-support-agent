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


class Tenant(Base):
    """A shop that embeds the chat widget. `api_key` is public (it ships in the
    widget's script URL) and only identifies the tenant; proving a visitor is who
    they claim takes a token signed with one of the tenant's `TenantSecret`s."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    api_key: Mapped[str] = mapped_column(unique=True, index=True)
    # Per-identity-level scope overrides, e.g. {"order_lookup": ["kb:read"]};
    # absent levels keep `app.auth.scopes.DEFAULT_LEVEL_SCOPES`.
    scope_overrides: Mapped[dict | None] = mapped_column(JSON)
    # The pages (origins) the shop's widget runs on. A browser request carrying another
    # origin is refused; see `app.api.origins`.
    allowed_origins: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @validates("allowed_origins")
    def _normalize_origins(self, _key: str, origins: list[str]) -> list[str]:
        """Normalized on the way in, and a wildcard or sloppy entry is an error, not a
        silent widening of who may use the key."""
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
    """The mail server a tenant's one-time codes go out through. The password is stored
    encrypted (`app.core.secrets`) and is write-only: nothing reads it back except the sender."""

    __tablename__ = "tenant_smtp"
    __table_args__ = (CheckConstraint("security in ('starttls', 'ssl', 'none')", name="ck_tenant_smtp_security"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    host: Mapped[str]
    port: Mapped[int]
    security: Mapped[str] = mapped_column(default="starttls")  # starttls | ssl | none
    username: Mapped[str | None]
    password_encrypted: Mapped[str | None]
    from_address: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantSecret(Base):
    """A signing secret we issued to a tenant. Several can be active at once so
    a shop can rotate without downtime; `kid` (in the token header) picks one."""

    __tablename__ = "tenant_secrets"
    __table_args__ = (UniqueConstraint("tenant_id", "kid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    kid: Mapped[str]
    # Stored in the clear: HS256 verification needs the raw key, so it can't be
    # hashed like a password. Encrypting it at rest is a follow-up.
    secret: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="secrets")


class Conversation(Base):
    """Who is talking, anchored server-side. Starts anonymous (no customer) and gets
    one when the visitor identifies; a customer already attached is never replaced
    (see `app.auth.conversations`). Sessions point at a conversation, and traces and
    security events use its id, instead of anything the client picks."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    identity_level: Mapped[str] = mapped_column(default="anonymous")
    linked_via: Mapped[str | None]  # how the customer was identified: store_login | otp_login
    customer_linked_at: Mapped[datetime | None]
    created_at: Mapped[datetime]
    # What the retention job reads to decide which conversations are old.
    last_activity_at: Mapped[datetime]
    last_seq: Mapped[int] = mapped_column(default=0, server_default="0")  # last message number
    # While an agent turn runs: when it started and a token unique to that run, so a second
    # message can't start another and a turn that lost the conversation can't write.
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # A person takes over from the assistant (see `app.chat.handoff`): `none` (the assistant
    # answers), `waiting` (a ticket was opened, no agent has joined) or `active` (an agent is in).
    handoff_status: Mapped[str] = mapped_column(default="none", server_default="none")
    # A return the customer is in the middle of (see `app.agent.nodes.order_return`): which order
    # and whether they were offered to keep it or asked to confirm cancelling it.
    pending_return_order_id: Mapped[str | None]
    pending_return_stage: Mapped[str | None]
    pending_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_agent_name: Mapped[str | None]  # the name the visitor sees, while `active`
    handoff_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL")
    )


class Message(Base):
    """One message of a conversation, stored server-side so the client can't forge the
    history. `client_message_id` (user messages) makes a retry idempotent."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
        UniqueConstraint(
            "conversation_id", "client_message_id", name="uq_messages_conversation_client_id"
        ),
        # One reply per user message (NULLs, i.e. user messages, never collide).
        UniqueConstraint("conversation_id", "reply_to_seq", name="uq_messages_conversation_reply"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # No separate index: the unique (conversation_id, seq) one serves lookups by conversation.
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    seq: Mapped[int]
    role: Mapped[str]  # user | assistant | human (a person from the back office) | system
    # The name a person's message is shown under; null for the assistant and the visitor.
    author_name: Mapped[str | None]
    # Cards shown with a reply (see `app.schemas.cards`), stored so a reload shows them again.
    cards: Mapped[list | None] = mapped_column(JSON)
    # text | identity_request | system. Anything but text is a form the widget shows (and an audit
    # record), not conversation: it is kept out of the history the model receives.
    kind: Mapped[str] = mapped_column(server_default="text", default="text")
    content: Mapped[str] = mapped_column(Text)
    client_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # On a reply: the seq of the user message it answers (found by this link, not position).
    reply_to_seq: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OtpChallenge(Base):
    """A one-time code sent to a customer's email (passwordless login). Only an HMAC
    of the code is stored. Dies when consumed, expired, superseded or out of attempts."""

    __tablename__ = "otp_challenges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(index=True)  # normalized: stripped, lowercased
    code_hash: Mapped[str]
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(default=0)
    consumed_at: Mapped[datetime | None]


class SecurityEvent(Base):
    """Something worth a human's review (too many wrong codes, requests over the
    limit). A signal, not a verdict: nothing is blocked by it."""

    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(index=True)
    email: Mapped[str | None]
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IdentificationEvent(Base):
    """One attempt to identify, for a person to read later: how (a code, an order, the shop's
    login), what came of it and, for a failure, why. The reason stays in this table: the visitor
    is always told the same generic thing.

    Holds nothing that could be used to get in: no code, no token, no full email and no full order
    id. The email is masked so a person can recognise it, and an HMAC of it (and of an order id)
    lets attempts by the same address be grouped without keeping it. See `app.auth.audit`."""

    __tablename__ = "identification_events"
    __table_args__ = (Index("ix_identification_events_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    # Set when the attempt proved a customer (a code, the shop's login); never for an order.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL")
    )
    method: Mapped[str]  # otp | order_id | store_login
    outcome: Mapped[str]  # code_sent | succeeded | failed
    reason: Mapped[str | None]
    email_masked: Mapped[str | None]
    email_hmac: Mapped[str | None] = mapped_column(index=True)
    order_hmac: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class RateLimitCounter(Base):
    """How many requests a key (an address, a conversation) made in one fixed time
    window. In Postgres rather than memory so every server instance shares the count."""

    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)

    # Indexed for the cleanup of windows that ended long ago.
    __table_args__ = (Index("ix_rate_limit_counters_window_start", "window_start"),)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_customers_tenant_external"),
        UniqueConstraint("tenant_id", "email", name="uq_customers_tenant_email"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    # `tenant_id`/`external_id` link a customer to the shop that vouches for them:
    # `external_id` is the `sub` in that shop's login token. Both are null for
    # customers that predate multi-tenancy.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    external_id: Mapped[str | None]
    # Unique per tenant (see `uq_customers_tenant_email`), not globally: two shops
    # can each have a customer with the same email.
    email: Mapped[str] = mapped_column(index=True)
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


class Order(Base):
    """A purchase of a plan. In the real product these come from the shop's own orders API
    (`app.orders.source`); this table is the simulated stand-in."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # What a customer is given and quotes: 20 alphanumeric characters, unique across tenants.
    order_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    amount_cents: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    status: Mapped[str] = mapped_column(default="paid")  # app.schemas.orders.OrderStatus
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    customer: Mapped["Customer"] = relationship()
    plan: Mapped["Plan"] = relationship()
    adjustment: Mapped["OrderAdjustment | None"] = relationship(uselist=False)


class OrderAdjustment(Base):
    """What a customer took to keep an order they wanted to reject. Simulated like `Order`: the
    shop's own system would hold it, and nothing here moves money. One per order."""

    __tablename__ = "order_adjustments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True)
    kind: Mapped[str]  # refund_to_card | credits
    refund_cents: Mapped[int | None]
    credit_points: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


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
