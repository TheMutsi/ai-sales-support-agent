import uuid
from datetime import UTC, datetime

from app.agent.nodes._identity import require_customer_id
from app.agent.state import AgentState
from app.business.escalation import RoutingFacts, decide_route
from app.chat.presence import count_available
from app.core.tenant_config import tenant_configs
from app.db.session import SessionLocal
from app.schemas.agent import Intent
from app.schemas.tools import EscalationCategory, EscalationReceipt
from app.tools.escalation import new_reference

# Deterministic lookup, no LLM call needed since `intent` is already
# classified by this point in the graph.
_INTENT_CATEGORY = {
    Intent.REFUND_REQUEST: EscalationCategory.REFUND,
    Intent.TECHNICAL_SUPPORT: EscalationCategory.TECHNICAL,
    Intent.BILLING_QUESTION: EscalationCategory.BILLING,
    Intent.HUMAN_ESCALATION: EscalationCategory.ESCALATION,
}


def human_escalation_node(state: AgentState) -> dict:
    """Escalates the conversation to a person, and decides which kind: one who joins the chat now
    or one who follows up later (`app.business.escalation`). There is no summary to write: whoever
    takes it reads the conversation, which is short. The follow-up number is kept on the
    conversation when the turn is saved."""
    require_customer_id(state)  # without a customer there is nothing to follow up
    if existing := state.get("open_escalation"):
        return {"escalation_receipt": existing, "escalated": True}
    tenant_id = uuid.UUID(state["tenant_id"])
    config = tenant_configs.get(tenant_id)
    now = datetime.now(UTC)
    result = state.get("return_result")
    order = (result.order if result else None) or state.get("order_details")
    with SessionLocal() as db:
        agents = count_available(db, tenant_id=tenant_id, now=now)
    decision = decide_route(
        RoutingFacts(
            now=now,
            support_hours=config.support_hours if config else None,
            agents_available=agents,
            order_status=order.status if order else None,
        )
    )
    receipt = EscalationReceipt(
        reference=new_reference(),
        route=decision.route,
        reason=decision.reason,
        category=_INTENT_CATEGORY.get(state["intent"], EscalationCategory.OTHER),
    )
    return {"escalation_receipt": receipt, "escalated": True}
