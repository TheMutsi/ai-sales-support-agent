from app.agent.state import AgentState
from app.tools.plans import list_plans


def get_plan_catalog_node(state: AgentState) -> dict:
    """Loads list prices deterministically for `pricing_question`, so the
    price in the answer comes from the plans table, never from the model."""
    return {"plan_catalog": list_plans()}
