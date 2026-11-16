from enum import StrEnum


class Node(StrEnum):
    INPUT_GUARDRAIL = "input_guardrail"
    INTENT_ROUTER = "intent_router"
    SAFETY_JUDGE = "safety_judge"
    GET_CUSTOMER_CONTEXT = "get_customer_context"
    BUSINESS_RULES = "business_rules"
    GET_PLAN_CATALOG = "get_plan_catalog"
    GET_ORDER_STATUS = "get_order_status"
    GET_CUSTOMER_ORDERS = "get_customer_orders"
    ORDER_RETURN = "order_return"
    KNOWLEDGE_TOOL = "knowledge_tool"
    ASK_CASE = "ask_case"
    HUMAN_ESCALATION = "human_escalation"
    REQUEST_IDENTITY = "request_identity"
    RESPONSE_WRITER = "response_writer"
    GUARDRAIL = "guardrail"
