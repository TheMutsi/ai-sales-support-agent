import uuid

from app.agent.nodes._identity import require_order_id
from app.agent.state import AgentState
from app.orders.factory import get_order_source


async def get_order_status_node(state: AgentState) -> dict:
    """Reads the one order the session proved, from the shop's orders (async: the real source
    is a network call). The tenant and the order id come from the session, never from the
    message, so what the visitor types cannot pick which order is read."""
    order_id = require_order_id(state)
    order = await get_order_source().get_order(
        tenant_id=uuid.UUID(state["tenant_id"]), order_id=order_id
    )
    return {"order_details": order}
