"""Typed contracts for the agent-facing tools layer (`app/tools/`).

Tool *inputs* are plain typed function parameters, not Pydantic models — these
functions are meant to be wrapped by LangChain's `@tool` decorator (Stage 6),
which derives its own args schema from type hints and docstrings, so a
parallel Input model here would just duplicate that. Tool *outputs* are
Pydantic models: each one is a multi-field result the agent, the frontend,
and observability all need a stable shape for, which a bare tuple or dict
wouldn't give them (Core Principle #3).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.schemas.business import PriceQuote


class PlanSummary(BaseModel):
    slug: str
    name: str
    price_cents: int
    billing_period: str
    seat_limit: int | None
    api_call_limit: int | None
    features: list[str]


class SubscriptionSummary(BaseModel):
    status: str
    current_period_end: datetime
    canceled_at: datetime | None
    plan: PlanSummary


class CustomerContext(BaseModel):
    """The customer-scoped facts a tool call needs but the LLM should never
    invent: identity, status, and current commercial state. `subscription` is
    `None` for a customer with no subscription row yet."""

    customer_id: uuid.UUID
    name: str
    email: str
    company: str | None
    status: str
    subscription: SubscriptionSummary | None


class CheckoutSession(BaseModel):
    """A simulated checkout — AcmeFlow has no real payment processor, so
    `checkout_url` is a fake link, not something that should ever be followed."""

    checkout_url: str
    target_plan_slug: str
    price_quote: PriceQuote


class TicketCategory(StrEnum):
    ESCALATION = "escalation"
    REFUND = "refund"
    TECHNICAL = "technical"
    BILLING = "billing"
    OTHER = "other"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TicketReceipt(BaseModel):
    ticket_id: uuid.UUID
    status: str
    created_at: datetime
