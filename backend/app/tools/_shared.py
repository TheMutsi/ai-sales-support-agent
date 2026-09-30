"""Private lookup helpers shared across `app/tools/` modules.

Every tool needs "find this row or fail loudly" — a missing customer_id or
plan_slug is the agent (or the LLM) passing a bad argument, not a system
failure, so it's raised as `ToolLookupError` once here instead of each tool
module re-deriving its own not-found message.
"""

import uuid

from sqlalchemy.orm import Session, joinedload

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
    construction.

    Eager-loads `.plan`: every caller of this helper immediately reads
    `subscription.plan` (to build a `PlanSummary`, price a quote, or read a
    slug), so leaving it lazy would turn one lookup into two queries every
    time.
    """
    return (
        session.query(Subscription)
        .options(joinedload(Subscription.plan))
        .filter_by(customer_id=customer_id)
        .order_by(Subscription.started_at.desc())
        .first()
    )


def require_current_subscription(session: Session, customer_id: uuid.UUID) -> Subscription:
    # Confirms the customer itself exists first, so a bad customer_id raises
    # "no customer" rather than the more ambiguous "no subscription" — the
    # latter would otherwise also fire for a customer that's never had one.
    require_customer(session, customer_id)
    subscription = current_subscription(session, customer_id)
    if subscription is None:
        raise ToolLookupError(f"No subscription found for customer {customer_id}")
    return subscription


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
