from typing import Literal

from langgraph.graph import END

from app.agent.names import Node
from app.agent.permissions import REQUIRED_SCOPE
from app.agent.pushback import asked_for_case
from app.agent.state import AgentState
from app.auth.scopes import Scope
from app.schemas.agent import Intent
from app.schemas.orders import ReturnOutcome

_SAFETY_CONFIDENCE_THRESHOLD = 0.95

_MAX_TOOL_CALL_ROUNDS = 2

_RETURN_FOLLOW_UPS = frozenset({Intent.ORDER_RETURN, Intent.SMALL_TALK})


_ANSWERED_BY_THE_WRITER_INTENTS = frozenset(
    {Intent.PRODUCT_QUESTION, Intent.TECHNICAL_SUPPORT, Intent.SMALL_TALK}
)
_ACCOUNT_CONTEXT_INTENTS = frozenset(
    {Intent.UPGRADE_REQUEST, Intent.BILLING_QUESTION, Intent.REFUND_REQUEST}
)


def _granted_scopes(state: AgentState) -> set[str]:
    return set(state.get("scopes") or [])


def _may_act_on_own_orders(state: AgentState, scopes: set[str]) -> bool:
    return bool(state.get("customer_id")) and Scope.REFUND_REQUEST in scopes


def _continues_pending_return(state: AgentState, scopes: set[str]) -> bool:
    return (
        state.get("pending_return") is not None
        and _may_act_on_own_orders(state, scopes)
        and state["intent"] in _RETURN_FOLLOW_UPS
    )


def route_start(state: AgentState) -> Literal[Node.INPUT_GUARDRAIL, Node.ORDER_RETURN]:
    is_trusted_click = state.get("action") is not None and _may_act_on_own_orders(
        state, _granted_scopes(state)
    )
    return Node.ORDER_RETURN if is_trusted_click else Node.INPUT_GUARDRAIL


def route_after_input_guardrail(state: AgentState) -> Literal["__end__", Node.INTENT_ROUTER]:
    return END if state["input_blocked"] else Node.INTENT_ROUTER


def route_after_intent(
    state: AgentState,
) -> Literal[
    Node.GET_CUSTOMER_CONTEXT,
    Node.GET_PLAN_CATALOG,
    Node.GET_ORDER_STATUS,
    Node.GET_CUSTOMER_ORDERS,
    Node.ORDER_RETURN,
    Node.ASK_CASE,
    Node.RESPONSE_WRITER,
    Node.HUMAN_ESCALATION,
    Node.REQUEST_IDENTITY,
    Node.SAFETY_JUDGE,
]:
    if (
        state["safety_confidence"] < _SAFETY_CONFIDENCE_THRESHOLD
        or state["intent"] == Intent.UNSUPPORTED
    ):
        return Node.SAFETY_JUDGE
    return _dispatch_by_intent(state)


def route_after_safety_judge(
    state: AgentState,
) -> Literal[
    Node.GET_CUSTOMER_CONTEXT,
    Node.GET_PLAN_CATALOG,
    Node.GET_ORDER_STATUS,
    Node.GET_CUSTOMER_ORDERS,
    Node.ORDER_RETURN,
    Node.ASK_CASE,
    Node.RESPONSE_WRITER,
    Node.HUMAN_ESCALATION,
    Node.REQUEST_IDENTITY,
    "__end__",
]:
    return END if state["input_blocked"] else _dispatch_by_intent(state)


def _dispatch_by_intent(
    state: AgentState,
) -> Literal[
    Node.GET_CUSTOMER_CONTEXT,
    Node.GET_PLAN_CATALOG,
    Node.GET_ORDER_STATUS,
    Node.GET_CUSTOMER_ORDERS,
    Node.ORDER_RETURN,
    Node.ASK_CASE,
    Node.RESPONSE_WRITER,
    Node.HUMAN_ESCALATION,
    Node.REQUEST_IDENTITY,
]:
    scopes = _granted_scopes(state)
    if _continues_pending_return(state, scopes):
        return Node.ORDER_RETURN
    if state["intent"] == Intent.UNSUPPORTED:
        return Node.HUMAN_ESCALATION if Scope.TICKET_CREATE in scopes else Node.RESPONSE_WRITER
    if REQUIRED_SCOPE[state["intent"]] not in scopes:
        return Node.REQUEST_IDENTITY
    if state["intent"] == Intent.HUMAN_ESCALATION and not asked_for_case(
        state.get("messages") or []
    ):
        return Node.ASK_CASE
    if state["intent"] == Intent.ORDER_RETURN:
        return Node.ORDER_RETURN if state.get("customer_id") else Node.REQUEST_IDENTITY
    if state["intent"] == Intent.ORDER_STATUS:
        if state.get("order_id"):
            return Node.GET_ORDER_STATUS
        return Node.GET_CUSTOMER_ORDERS if state.get("customer_id") else Node.REQUEST_IDENTITY
    if state["intent"] in _ACCOUNT_CONTEXT_INTENTS:
        return Node.GET_CUSTOMER_CONTEXT
    if state["intent"] == Intent.PRICING_QUESTION:
        return Node.GET_PLAN_CATALOG
    if state["intent"] in _ANSWERED_BY_THE_WRITER_INTENTS:
        return Node.RESPONSE_WRITER
    return Node.HUMAN_ESCALATION


def route_after_order_return(state: AgentState) -> Literal[Node.HUMAN_ESCALATION, "__end__"]:
    result = state.get("return_result")
    return Node.HUMAN_ESCALATION if result and result.outcome is ReturnOutcome.ESCALATED else END


def route_after_response_writer(
    state: AgentState,
) -> Literal[Node.KNOWLEDGE_TOOL, Node.GUARDRAIL]:
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if tool_calls and state.get("tool_call_rounds", 0) < _MAX_TOOL_CALL_ROUNDS:
        return Node.KNOWLEDGE_TOOL
    return Node.GUARDRAIL


def route_after_customer_context(
    state: AgentState,
) -> Literal[Node.BUSINESS_RULES, Node.RESPONSE_WRITER, Node.HUMAN_ESCALATION]:
    if state["intent"] == Intent.UPGRADE_REQUEST:
        return Node.BUSINESS_RULES
    if state["intent"] == Intent.BILLING_QUESTION:
        return Node.RESPONSE_WRITER
    return Node.HUMAN_ESCALATION
