"""Private lookup helpers shared across `app/tools/` modules.

Every tool needs "find this row or fail loudly" — a missing customer_id or
plan_slug is the agent (or the LLM) passing a bad argument, not a system
failure, so it's raised as `ToolLookupError` once here instead of each tool
module re-deriving its own not-found message.
"""

import uuid

from sqlalchemy.orm import Session

from app.db.models import Customer, Plan, Subscription
from app.schemas.tools import PlanSummary
from app.tools.errors import ToolLookupError


def require_customer(session: Session, customer_id: uuid.UUID) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise ToolLookupError(f"No customer with id {customer_id}")
    return customer


def require_plan(session: Session, plan_slug: str) -> Plan:
    plan = session.query(Plan).filter_by(slug=plan_slug).one_or_none()
    if plan is None:
        raise ToolLookupError(f"No plan with slug {plan_slug!r}")
    return plan


def current_subscription(session: Session, customer_id: uuid.UUID) -> Subscription | None:
    """The customer's most recent subscription row. `Subscription` has no
    explicit "is this the current one" flag (see its docstring in
    db/models.py) — a new row is added when a customer's commercial state
    changes, so the most recently started one is the current state by
    construction."""
    return (
        session.query(Subscription)
        .filter_by(customer_id=customer_id)
        .order_by(Subscription.started_at.desc())
        .first()
    )


def plan_summary(plan: Plan) -> PlanSummary:
    return PlanSummary(
        slug=plan.slug,
        name=plan.name,
        price_cents=plan.price_cents,
        billing_period=plan.billing_period,
        seat_limit=plan.seat_limit,
        api_call_limit=plan.api_call_limit,
        features=plan.features,
    )
