from app.agent.state import AgentState
from app.schemas.agent import Intent


def route_after_intent(state: AgentState) -> str:
    if state["intent"] in {Intent.UPGRADE_REQUEST, Intent.BILLING_QUESTION, Intent.REFUND_REQUEST}:
        return "get_customer_context"
    if state["intent"] in {
        Intent.PRODUCT_QUESTION,
        Intent.PRICING_QUESTION,
        Intent.TECHNICAL_SUPPORT,
    }:
        return "retrieve_knowledge"
    return "human_escalation"  # human_escalation and unsupported


def route_after_customer_context(state: AgentState) -> str:
    if state["intent"] == Intent.UPGRADE_REQUEST:
        return "business_rules"
    if state["intent"] == Intent.BILLING_QUESTION:
        return "response_writer"
    return "human_escalation"  # refund_request — no refund tool exists, so it always escalates
