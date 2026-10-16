"""Agent-facing tool: fetch a customer's identity and current commercial state.

Manages its own DB session — unlike `app/rag/retriever.py`, which is a
lower-level module the RAG pipeline threads a session through, tools are the
boundary the agent graph calls across, and `AgentState` (Stage 6) has no
place for a live SQLAlchemy session to live between nodes.
"""

import uuid

from app.db.models import Customer
from app.db.session import SessionLocal
from app.schemas.tools import CustomerContext, CustomerListItem, SubscriptionSummary
from app.tools._shared import current_subscription, plan_summary, require_customer


def get_customer_context(customer_id: uuid.UUID) -> CustomerContext:
    with SessionLocal() as session:
        customer = require_customer(session, customer_id)
        subscription = current_subscription(session, customer_id)

        subscription_summary = None
        if subscription is not None:
            subscription_summary = SubscriptionSummary(
                status=subscription.status,
                current_period_end=subscription.current_period_end,
                canceled_at=subscription.canceled_at,
                plan=plan_summary(subscription.plan),
            )

        return CustomerContext(
            customer_id=customer.id,
            name=customer.name,
            email=customer.email,
            company=customer.company,
            status=customer.status,
            subscription=subscription_summary,
        )


def list_customers() -> list[CustomerListItem]:
    """Every customer with their current plan, for the frontend's selector.
    Sorted by name so the list is stable between requests. One query per
    customer for the subscription is fine at demo scale; paginate and join
    before pointing this at a real customer base."""
    with SessionLocal() as session:
        items = []
        for customer in session.query(Customer).order_by(Customer.name).all():
            subscription = current_subscription(session, customer.id)
            plan = subscription.plan if subscription is not None else None
            items.append(
                CustomerListItem(
                    customer_id=customer.id,
                    name=customer.name,
                    company=customer.company,
                    status=customer.status,
                    plan_slug=plan.slug if plan else None,
                    plan_name=plan.name if plan else None,
                )
            )
        return items
