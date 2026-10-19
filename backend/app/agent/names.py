from enum import StrEnum


class Node(StrEnum):
    """Every node name in the agent graph, defined once.

    `graph.py` registers nodes under these names and `routing.py` returns them,
    so a typo is an `AttributeError` at import time instead of a bad edge at
    runtime. `StrEnum` members compare equal to their plain string value, so
    state, traces and tests that use the raw name keep working.
    """

    INPUT_GUARDRAIL = "input_guardrail"
    INTENT_ROUTER = "intent_router"
    SAFETY_JUDGE = "safety_judge"
    GET_CUSTOMER_CONTEXT = "get_customer_context"
    BUSINESS_RULES = "business_rules"
    GET_PLAN_CATALOG = "get_plan_catalog"
    GET_ORDER_STATUS = "get_order_status"
    GET_CUSTOMER_ORDERS = "get_customer_orders"
    KNOWLEDGE_TOOL = "knowledge_tool"
    HUMAN_ESCALATION = "human_escalation"
    REQUEST_IDENTITY = "request_identity"
    RESPONSE_WRITER = "response_writer"
    GUARDRAIL = "guardrail"
