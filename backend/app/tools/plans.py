from sqlalchemy import select

from app.db.models import Plan
from app.db.session import SessionLocal
from app.schemas.tools import PlanSummary
from app.tools._shared import plan_summary, require_plan


def get_plan_details(plan_slug: str) -> PlanSummary:
    with SessionLocal() as session:
        return plan_summary(require_plan(session, plan_slug))


def list_plans() -> list[PlanSummary]:
    with SessionLocal() as session:
        plans = session.scalars(select(Plan).order_by(Plan.price_cents)).all()
        return [plan_summary(plan) for plan in plans]
