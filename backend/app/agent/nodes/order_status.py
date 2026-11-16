import uuid

from app.agent.nodes._identity import require_order_id
from app.agent.state import AgentState
from app.orders.factory import get_order_source


async def get_order_status_node(state: AgentState) -> dict:
    order_id = require_order_id(state)
    order = await get_order_source().get_order(
        tenant_id=uuid.UUID(state["tenant_id"]), order_id=order_id
    )
    return {"order_details": order}


async def get_customer_orders_node(state: AgentState) -> dict:
    customer_id, tenant_id = state.get("customer_id"), state.get("tenant_id")
    if customer_id is None or tenant_id is None:
        raise ValueError("reading a customer's orders needs a verified customer")
    orders = await get_order_source().list_orders(
        tenant_id=uuid.UUID(tenant_id), customer_id=uuid.UUID(customer_id)
    )
    return {"customer_orders": orders}
