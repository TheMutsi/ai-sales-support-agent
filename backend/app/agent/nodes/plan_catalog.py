from app.agent.state import AgentState
from app.tools.plans import list_plans


def get_plan_catalog_node(state: AgentState) -> dict:
    return {"plan_catalog": list_plans()}
