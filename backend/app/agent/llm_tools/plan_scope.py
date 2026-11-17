import uuid

from app.agent.state import AgentState
from app.tools.knowledge_base import current_plan_slug


def resolve_plan_slug(state: AgentState) -> str | None:
    if "knowledge_plan_slug" in state:
        return state["knowledge_plan_slug"]
    if not state.get("customer_id"):
        return None
    if (context := state.get("customer_context")) is not None:
        return context.subscription.plan.slug if context.subscription is not None else None
    return current_plan_slug(uuid.UUID(str(state["customer_id"])))
