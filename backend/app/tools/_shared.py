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
    return (
        session.query(Subscription)
        .options(joinedload(Subscription.plan))
        .filter_by(customer_id=customer_id)
        .order_by(Subscription.started_at.desc())
        .first()
    )


def require_current_subscription(session: Session, customer_id: uuid.UUID) -> Subscription:
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
