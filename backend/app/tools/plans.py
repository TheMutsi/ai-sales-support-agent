"""Agent-facing tool: look up a plan's details by slug."""

from app.db.session import SessionLocal
from app.schemas.tools import PlanSummary
from app.tools._shared import plan_summary, require_plan


def get_plan_details(plan_slug: str) -> PlanSummary:
    with SessionLocal() as session:
        return plan_summary(require_plan(session, plan_slug))
