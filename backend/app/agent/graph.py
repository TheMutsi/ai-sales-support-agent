from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from app.agent.names import Node
from app.agent.nodes.business_rules import business_rules_node
from app.agent.nodes.customer_context import get_customer_context_node
from app.agent.nodes.guardrail import guardrail_node
from app.agent.nodes.human_escalation import human_escalation_node
from app.agent.nodes.input_guardrail import input_guardrail_node
from app.agent.nodes.intent_router import intent_router
from app.agent.nodes.knowledge_tool import knowledge_tool_node
from app.agent.nodes.order_return import order_return_node
from app.agent.nodes.order_status import get_customer_orders_node, get_order_status_node
from app.agent.nodes.plan_catalog import get_plan_catalog_node
from app.agent.nodes.request_identity import request_identity_node
from app.agent.nodes.response_writer import response_writer_node
from app.agent.nodes.safety_judge import safety_judge_node
from app.agent.routing import (
    route_after_customer_context,
    route_after_input_guardrail,
    route_after_intent,
    route_after_response_writer,
    route_after_safety_judge,
)
from app.agent.state import AgentState


def build_graph(checkpointer: Checkpointer = None):
    """Assemble and compile the agent graph.

    A function rather than module-level wiring so tests can build a fresh graph
    (with a checkpointer, say) and importing this module has no side effects
    beyond the one `graph` below. Destinations of the conditional edges come
    from the `Literal` return types in `routing.py`, so LangGraph validates
    them at compile time and `get_graph().draw_mermaid()` shows every edge.
    """
    builder = StateGraph(AgentState)
    builder.add_node(Node.INPUT_GUARDRAIL, input_guardrail_node)
    builder.add_node(Node.INTENT_ROUTER, intent_router)
    builder.add_node(Node.SAFETY_JUDGE, safety_judge_node)
    builder.add_node(Node.GET_CUSTOMER_CONTEXT, get_customer_context_node)
    builder.add_node(Node.BUSINESS_RULES, business_rules_node)
    builder.add_node(Node.GET_PLAN_CATALOG, get_plan_catalog_node)
    builder.add_node(Node.GET_ORDER_STATUS, get_order_status_node)
    builder.add_node(Node.GET_CUSTOMER_ORDERS, get_customer_orders_node)
    builder.add_node(Node.ORDER_RETURN, order_return_node)
    builder.add_node(Node.KNOWLEDGE_TOOL, knowledge_tool_node)
    builder.add_node(Node.HUMAN_ESCALATION, human_escalation_node)
    builder.add_node(Node.REQUEST_IDENTITY, request_identity_node)
    builder.add_node(Node.RESPONSE_WRITER, response_writer_node)
    builder.add_node(Node.GUARDRAIL, guardrail_node)

    builder.add_edge(START, Node.INPUT_GUARDRAIL)
    builder.add_conditional_edges(Node.INPUT_GUARDRAIL, route_after_input_guardrail)
    builder.add_conditional_edges(Node.INTENT_ROUTER, route_after_intent)
    builder.add_conditional_edges(Node.SAFETY_JUDGE, route_after_safety_judge)
    builder.add_conditional_edges(Node.GET_CUSTOMER_CONTEXT, route_after_customer_context)
    builder.add_edge(Node.BUSINESS_RULES, Node.RESPONSE_WRITER)
    builder.add_edge(Node.GET_PLAN_CATALOG, Node.RESPONSE_WRITER)
    builder.add_edge(Node.GET_ORDER_STATUS, Node.RESPONSE_WRITER)
    builder.add_edge(Node.GET_CUSTOMER_ORDERS, Node.RESPONSE_WRITER)
    # The step writes its own reply (fixed text), so no model words it and nothing is checked after.
    builder.add_edge(Node.ORDER_RETURN, END)
    builder.add_edge(Node.HUMAN_ESCALATION, Node.RESPONSE_WRITER)
    builder.add_conditional_edges(Node.RESPONSE_WRITER, route_after_response_writer)
    builder.add_edge(Node.KNOWLEDGE_TOOL, Node.RESPONSE_WRITER)
    builder.add_edge(Node.REQUEST_IDENTITY, END)
    builder.add_edge(Node.GUARDRAIL, END)
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
