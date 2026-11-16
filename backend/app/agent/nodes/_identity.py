from app.agent.state import AgentState


def require_customer_id(state: AgentState) -> str:
    customer_id = state.get("customer_id")
    if customer_id is None:
        raise PermissionError("this step needs an identified customer")
    return customer_id


def require_order_id(state: AgentState) -> str:
    order_id = state.get("order_id")
    if order_id is None or state.get("tenant_id") is None:
        raise PermissionError("this step needs an order proved by the session")
    return order_id

