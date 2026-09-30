from app.agent.state import AgentState
from app.tools.customers import get_customer_context


def get_customer_context_node(state: AgentState) -> dict:
    context = get_customer_context(state["customer_id"])
    return {"customer_context": context}
