from langgraph.graph import END

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
    # human_escalation and unsupported — no human_escalation node yet (next PR), so
    # these just end the graph for now instead of producing a final answer.
    return END


def route_after_customer_context(state: AgentState) -> str:
    if state["intent"] == Intent.UPGRADE_REQUEST:
        return "business_rules"
    # billing_question and refund_request — no response_writer/human_escalation node
    # yet (next PR); ends the graph for now.
    return END
