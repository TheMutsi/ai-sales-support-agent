import uuid
from datetime import UTC, datetime

from app.agent.nodes._identity import require_customer_id
from app.agent.state import AgentState
from app.business.escalation import EscalationRoute, RouteDecision, RoutingFacts, decide_route
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
    conversation when the turn is saved.

    A conversation keeps one open escalation and its number. An open offline one becomes live, with
    the same number, once someone can join; a live one stays as it is."""
    require_customer_id(state)  # without a customer there is nothing to follow up
    existing = state.get("open_escalation")
    if existing is not None and existing.route is EscalationRoute.LIVE:
        return {"escalation_receipt": existing, "escalated": True}
    decision = _decide(state)
    if existing is not None:
        if decision.route is EscalationRoute.LIVE:
            existing = existing.model_copy(update={"route": decision.route, "reason": decision.reason})
        return {"escalation_receipt": existing, "escalated": True}
    receipt = EscalationReceipt(
        reference=new_reference(),
        route=decision.route,
        reason=decision.reason,
        category=_INTENT_CATEGORY.get(state["intent"], EscalationCategory.OTHER),
    )
    return {"escalation_receipt": receipt, "escalated": True}


def _decide(state: AgentState) -> RouteDecision:
    tenant_id = uuid.UUID(state["tenant_id"])
    config = tenant_configs.get(tenant_id)
    now = datetime.now(UTC)
    result = state.get("return_result")
    order = (result.order if result else None) or state.get("order_details")
    with SessionLocal() as db:
        agents = count_available(db, tenant_id=tenant_id, now=now)
    return decide_route(
        RoutingFacts(
            now=now,
            support_hours=config.support_hours if config else None,
            agents_available=agents,
            order_status=order.status if order else None,
        )
    )
