from langgraph.graph import END

from app.agent.state import AgentState
from app.schemas.agent import Intent

# Below this, intent_router's own safety_confidence (scored in the same call
# as intent, so it's free) isn't enough on its own — route to safety_judge
# for a dedicated second opinion instead of dispatching on a guess.
# Calibrated on the evaluation dev set (qwen2.5:7b-instruct), not guessed: the
# router scores almost every message 0.9 or 1.0, so 0.7 sent only 4 of 6
# regex-evading attempts to the judge; 0.95 sent all 6, and 2 of 44 legitimate
# messages (the judge then allowed both). One sample with clustered scores,
# so re-check it with `run_eval`'s threshold sweep after any model change.
_SAFETY_CONFIDENCE_THRESHOLD = 0.95

# How many LLM↔tool round trips `response_writer` can take in one turn before
# `route_after_response_writer` forces it to `guardrail` regardless of
# whether the model still wants to call the tool — a deliberate, testable cap
# instead of relying only on LangGraph's generic recursion limit.
_MAX_TOOL_CALL_ROUNDS = 2


def route_after_input_guardrail(state: AgentState) -> str:
    return END if state["input_blocked"] else "intent_router"


def route_after_intent(state: AgentState) -> str:
    # `unsupported` always gets the second look, whatever the score: it is the
    # residual class misuse lands in when it isn't a recognizable support
    # request, and its route opens a support ticket, a side effect. The eval
    # dev set caught phishing and other-customer-data requests scored 0.95-1.0,
    # classified unsupported, that safety_judge blocks in isolation.
    if (
        state["safety_confidence"] < _SAFETY_CONFIDENCE_THRESHOLD
        or state["intent"] == Intent.UNSUPPORTED
    ):
        return "safety_judge"
    return _dispatch_by_intent(state)


def route_after_safety_judge(state: AgentState) -> str:
    return END if state["input_blocked"] else _dispatch_by_intent(state)


def _dispatch_by_intent(state: AgentState) -> str:
    if state["intent"] in {Intent.UPGRADE_REQUEST, Intent.BILLING_QUESTION, Intent.REFUND_REQUEST}:
        return "get_customer_context"
    if state["intent"] == Intent.PRICING_QUESTION:
        # Prices live only in the plans table, so they are loaded
        # deterministically before the answer; the KB tool stays bound for
        # pricing policy (discounts, quotes) the catalog doesn't cover.
        return "get_plan_catalog"
    if state["intent"] in {Intent.PRODUCT_QUESTION, Intent.TECHNICAL_SUPPORT}:
        # No deterministic prefetch here (that was `retrieve_knowledge`,
        # removed): for these three intents `response_writer` binds the
        # knowledge-base search as a real tool call and the LLM decides
        # whether/how to use it, instead of the graph always fetching first.
        return "response_writer"
    return "human_escalation"  # human_escalation and unsupported


def route_after_response_writer(state: AgentState) -> str:
    """`response_writer` only has a tool bound for the RAG-eligible intents
    (see `_RAG_ELIGIBLE_INTENTS`), so `tool_calls` is only non-empty there —
    every other intent's response has nothing to check here and goes
    straight to `guardrail`, same as before this node could loop."""
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if tool_calls and state.get("tool_call_rounds", 0) < _MAX_TOOL_CALL_ROUNDS:
        return "knowledge_tool"
    return "guardrail"


def route_after_customer_context(state: AgentState) -> str:
    if state["intent"] == Intent.UPGRADE_REQUEST:
        return "business_rules"
    if state["intent"] == Intent.BILLING_QUESTION:
        return "response_writer"
    return "human_escalation"  # refund_request — no refund tool exists, so it always escalates
