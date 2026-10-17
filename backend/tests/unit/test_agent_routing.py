"""Unit tests for the agent graph's conditional-edge routing functions.

`route_after_intent` and `route_after_customer_context` are plain functions
over a `state` dict — no LLM, no DB, no graph compilation needed to exercise
them, the same way the business-rules tests construct their inputs directly.
"""

from langchain_core.messages import AIMessage
from langgraph.graph import END

from app.agent.routing import (
    route_after_customer_context,
    route_after_input_guardrail,
    route_after_intent,
    route_after_response_writer,
    route_after_safety_judge,
)
from app.auth.scopes import IdentityLevel, scopes_for
from app.schemas.agent import Intent

_CUSTOMER_SCOPES = sorted(scopes_for(IdentityLevel.STORE_LOGIN))
_ANONYMOUS_SCOPES = sorted(scopes_for(IdentityLevel.ANONYMOUS))
_ORDER_LOOKUP_SCOPES = sorted(scopes_for(IdentityLevel.ORDER_LOOKUP))


def _state(intent: Intent, safety_confidence: float = 1.0, scopes=_CUSTOMER_SCOPES) -> dict:
    return {"intent": intent, "safety_confidence": safety_confidence, "scopes": scopes}


def test_blocked_input_goes_straight_to_end():
    assert route_after_input_guardrail({"input_blocked": True}) == END


def test_clean_input_goes_to_intent_router():
    assert route_after_input_guardrail({"input_blocked": False}) == "intent_router"


def test_low_safety_confidence_goes_to_safety_judge_regardless_of_intent():
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION, safety_confidence=0.4)) == (
        "safety_judge"
    )


def test_high_safety_confidence_dispatches_normally():
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION, safety_confidence=1.0)) == (
        "response_writer"
    )


def test_a_typical_unsure_score_still_gets_a_second_look():
    """Regression: qwen2.5 scores nearly everything 0.9 or 1.0, so the old 0.7
    threshold let regex-evading misuse attempts scored 0.9 skip safety_judge."""
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION, safety_confidence=0.9)) == (
        "safety_judge"
    )


def test_unsupported_gets_a_second_look_even_with_full_safety_confidence():
    """Regression: phishing and other-customers'-data requests were scored
    0.95-1.0, classified unsupported, and opened a support ticket."""
    assert route_after_intent(_state(Intent.UNSUPPORTED, safety_confidence=1.0)) == ("safety_judge")


def test_safety_judge_blocked_goes_straight_to_end():
    assert route_after_safety_judge({"input_blocked": True, "intent": Intent.PRODUCT_QUESTION}) == (
        END
    )


def test_safety_judge_cleared_dispatches_by_the_original_intent():
    state = {"input_blocked": False, "intent": Intent.UPGRADE_REQUEST, "scopes": _CUSTOMER_SCOPES}
    assert route_after_safety_judge(state) == "get_customer_context"


def test_upgrade_request_goes_to_customer_context():
    assert route_after_intent(_state(Intent.UPGRADE_REQUEST)) == "get_customer_context"


def test_billing_question_goes_to_customer_context():
    assert route_after_intent(_state(Intent.BILLING_QUESTION)) == "get_customer_context"


def test_refund_request_goes_to_customer_context():
    assert route_after_intent(_state(Intent.REFUND_REQUEST)) == "get_customer_context"


def test_product_question_goes_to_response_writer():
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION)) == "response_writer"


def test_pricing_question_loads_the_plan_catalog_first():
    assert route_after_intent(_state(Intent.PRICING_QUESTION)) == "get_plan_catalog"


def test_technical_support_goes_to_response_writer():
    assert route_after_intent(_state(Intent.TECHNICAL_SUPPORT)) == "response_writer"


def test_small_talk_is_answered_directly_without_opening_a_ticket():
    assert route_after_intent(_state(Intent.SMALL_TALK)) == "response_writer"
    state = {"input_blocked": False, "intent": Intent.SMALL_TALK, "scopes": _CUSTOMER_SCOPES}
    assert route_after_safety_judge(state) == "response_writer"


def test_human_escalation_goes_to_human_escalation():
    assert route_after_intent(_state(Intent.HUMAN_ESCALATION)) == "human_escalation"


def test_unsupported_cleared_by_safety_judge_goes_to_human_escalation():
    state = {"input_blocked": False, "intent": Intent.UNSUPPORTED, "scopes": _CUSTOMER_SCOPES}
    assert route_after_safety_judge(state) == "human_escalation"


def test_upgrade_request_goes_to_business_rules():
    assert route_after_customer_context(_state(Intent.UPGRADE_REQUEST)) == "business_rules"


def test_billing_question_goes_to_response_writer():
    assert route_after_customer_context(_state(Intent.BILLING_QUESTION)) == "response_writer"


def test_refund_request_goes_to_human_escalation():
    assert route_after_customer_context(_state(Intent.REFUND_REQUEST)) == "human_escalation"


def _tool_call(name: str = "search_knowledge_base_tool") -> dict:
    return {"name": name, "args": {"query": "pricing"}, "id": "call_1"}


def test_response_without_tool_calls_goes_to_guardrail():
    state = {"messages": [AIMessage(content="Here's the answer.")]}
    assert route_after_response_writer(state) == "guardrail"


def test_response_with_tool_calls_goes_to_knowledge_tool():
    state = {
        "messages": [AIMessage(content="", tool_calls=[_tool_call()])],
        "tool_call_rounds": 0,
    }
    assert route_after_response_writer(state) == "knowledge_tool"


def test_tool_calls_past_the_round_cap_go_to_guardrail_anyway():
    state = {
        "messages": [AIMessage(content="", tool_calls=[_tool_call()])],
        "tool_call_rounds": 2,
    }
    assert route_after_response_writer(state) == "guardrail"


def test_compiled_graph_exposes_every_conditional_destination():
    """The `Literal` return types give LangGraph the destinations, so the
    drawn graph has the real edges (not just nodes) and every routing target
    is a registered node."""
    from app.agent.graph import build_graph
    from app.agent.names import Node

    drawn = build_graph().get_graph()
    nodes = {n for n in drawn.nodes} - {"__start__", "__end__"}
    assert nodes == {n.value for n in Node}
    edges = {(e.source, e.target) for e in drawn.edges}
    assert ("response_writer", "knowledge_tool") in edges
    assert ("response_writer", "guardrail") in edges
    assert ("intent_router", "safety_judge") in edges
    assert ("input_guardrail", "__end__") in edges


def _anonymous(intent: Intent) -> dict:
    return _state(intent, scopes=_ANONYMOUS_SCOPES)


def test_an_anonymous_visitor_asking_about_their_account_is_asked_to_identify():
    for intent in (Intent.BILLING_QUESTION, Intent.UPGRADE_REQUEST, Intent.REFUND_REQUEST):
        assert route_after_intent(_anonymous(intent)) == "request_identity"


def test_an_anonymous_visitor_asking_for_a_human_is_asked_to_identify_first():
    assert route_after_intent(_anonymous(Intent.HUMAN_ESCALATION)) == "request_identity"


def test_an_anonymous_visitor_can_still_ask_about_the_product():
    assert route_after_intent(_anonymous(Intent.PRODUCT_QUESTION)) == "response_writer"
    assert route_after_intent(_anonymous(Intent.PRICING_QUESTION)) == "get_plan_catalog"
    assert route_after_intent(_anonymous(Intent.SMALL_TALK)) == "response_writer"


def test_an_off_topic_message_from_an_anonymous_visitor_is_answered_without_a_ticket():
    """A ticket needs a customer; asking someone to identify just to say no would be odd."""
    state = {"input_blocked": False, "intent": Intent.UNSUPPORTED, "scopes": _ANONYMOUS_SCOPES}

    assert route_after_safety_judge(state) == "response_writer"


def test_a_missing_scope_list_denies_instead_of_allowing():
    assert route_after_intent({"intent": Intent.BILLING_QUESTION, "safety_confidence": 1.0}) == (
        "request_identity"
    )


def test_the_safety_judge_still_runs_before_the_identity_request():
    assert route_after_intent(_state(Intent.BILLING_QUESTION, 0.4, _ANONYMOUS_SCOPES)) == (
        "safety_judge"
    )
    state = {"input_blocked": False, "intent": Intent.BILLING_QUESTION, "scopes": _ANONYMOUS_SCOPES}
    assert route_after_safety_judge(state) == "request_identity"


def test_someone_who_proved_only_an_order_is_asked_to_identify_for_anything_about_the_account():
    """The order level has no customer: account intents must route to `request_identity`
    (never into a node that needs a customer), whatever the order says."""
    for intent in (
        Intent.BILLING_QUESTION,
        Intent.UPGRADE_REQUEST,
        Intent.REFUND_REQUEST,
        Intent.HUMAN_ESCALATION,
    ):
        assert route_after_intent(_state(intent, scopes=_ORDER_LOOKUP_SCOPES)) == (
            "request_identity"
        )
    assert route_after_intent(_state(Intent.PRODUCT_QUESTION, scopes=_ORDER_LOOKUP_SCOPES)) == (
        "response_writer"
    )


def _asking_about_an_order(scopes, order_id=None) -> dict:
    return {**_state(Intent.ORDER_STATUS, scopes=scopes), "order_id": order_id}


def test_someone_who_proved_an_order_gets_that_order_looked_up():
    state = _asking_about_an_order(_ORDER_LOOKUP_SCOPES, order_id="a" * 20)

    assert route_after_intent(state) == "get_order_status"


def test_an_anonymous_visitor_asking_about_an_order_is_asked_to_identify():
    assert route_after_intent(_asking_about_an_order(_ANONYMOUS_SCOPES)) == "request_identity"


def test_a_customer_with_no_order_in_the_session_is_asked_for_one_not_given_a_guess():
    """A verified customer holds `order:read` but the session names no order: the agent must
    not pick one for them, so it asks for the order to look up."""
    assert route_after_intent(_asking_about_an_order(_CUSTOMER_SCOPES)) == "request_identity"


def test_the_order_lookup_goes_on_to_the_response_writer_in_the_compiled_graph():
    from app.agent.graph import build_graph

    edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("get_order_status", "response_writer") in edges

