import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.business.escalation import EscalationRoute, RouteReason
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
    customer_id: uuid.UUID
    name: str
    email: str
    company: str | None
    status: str
    subscription: SubscriptionSummary | None


class CustomerListItem(BaseModel):
    customer_id: uuid.UUID
    name: str
    company: str | None
    status: str
    plan_slug: str | None
    plan_name: str | None


class CheckoutSession(BaseModel):
    checkout_url: str
    target_plan_slug: str
    price_quote: PriceQuote


class EscalationCategory(StrEnum):
    ESCALATION = "escalation"
    REFUND = "refund"
    TECHNICAL = "technical"
    BILLING = "billing"
    OTHER = "other"


class EscalationReceipt(BaseModel):
    reference: str
    route: EscalationRoute
    reason: RouteReason
    category: EscalationCategory
