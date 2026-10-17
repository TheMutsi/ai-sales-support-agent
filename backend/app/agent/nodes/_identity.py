"""A node that works on a customer's account must never run without one."""

from app.agent.state import AgentState


def require_customer_id(state: AgentState) -> str:
    customer_id = state.get("customer_id")
    if customer_id is None:
        # Routing sends anonymous visitors to `request_identity` before any of these nodes;
        # reaching one is a bug, and failing here beats acting on an empty customer.
        raise PermissionError("this step needs an identified customer")
    return customer_id
