"""Agent-facing tools: look up one plan by slug, or the whole catalog."""

from sqlalchemy import select

from app.db.models import Plan
from app.db.session import SessionLocal
from app.schemas.tools import PlanSummary
from app.tools._shared import plan_summary, require_plan


def get_plan_details(plan_slug: str) -> PlanSummary:
    with SessionLocal() as session:
        return plan_summary(require_plan(session, plan_slug))


def list_plans() -> list[PlanSummary]:
    """Every plan, cheapest first. The plans table is the only source of
    prices: the knowledge base deliberately has none, so they cannot drift."""
    with SessionLocal() as session:
        plans = session.scalars(select(Plan).order_by(Plan.price_cents)).all()
        return [plan_summary(plan) for plan in plans]
