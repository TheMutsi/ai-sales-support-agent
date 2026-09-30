from langgraph.graph import END

from app.agent.state import AgentState
from app.schemas.agent import Intent

# Below this, intent_router's own safety_confidence (scored in the same call
# as intent, so it's free) isn't enough on its own — route to safety_judge
# for a dedicated second opinion instead of dispatching on a guess. Most
# messages score well above this and skip that extra LLM call entirely.
_SAFETY_CONFIDENCE_THRESHOLD = 0.7


def route_after_input_guardrail(state: AgentState) -> str:
    return END if state["input_blocked"] else "intent_router"


def route_after_intent(state: AgentState) -> str:
    if state["safety_confidence"] < _SAFETY_CONFIDENCE_THRESHOLD:
        return "safety_judge"
    return _dispatch_by_intent(state)


def route_after_safety_judge(state: AgentState) -> str:
    return END if state["input_blocked"] else _dispatch_by_intent(state)


def _dispatch_by_intent(state: AgentState) -> str:
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
