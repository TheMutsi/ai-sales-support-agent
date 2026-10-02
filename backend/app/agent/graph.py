from langgraph.graph import END, START, StateGraph

from app.agent.nodes.business_rules import business_rules_node
from app.agent.nodes.customer_context import get_customer_context_node
from app.agent.nodes.guardrail import guardrail_node
from app.agent.nodes.human_escalation import human_escalation_node
from app.agent.nodes.input_guardrail import input_guardrail_node
from app.agent.nodes.intent_router import intent_router
from app.agent.nodes.knowledge_tool import knowledge_tool_node
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

graph_builder = StateGraph(AgentState)
graph_builder.add_node("input_guardrail", input_guardrail_node)
graph_builder.add_node("intent_router", intent_router)
graph_builder.add_node("safety_judge", safety_judge_node)
graph_builder.add_node("get_customer_context", get_customer_context_node)
graph_builder.add_node("business_rules", business_rules_node)
graph_builder.add_node("knowledge_tool", knowledge_tool_node)
graph_builder.add_node("human_escalation", human_escalation_node)
graph_builder.add_node("response_writer", response_writer_node)
graph_builder.add_node("guardrail", guardrail_node)

graph_builder.add_edge(START, "input_guardrail")
graph_builder.add_conditional_edges("input_guardrail", route_after_input_guardrail)
graph_builder.add_conditional_edges("intent_router", route_after_intent)
graph_builder.add_conditional_edges("safety_judge", route_after_safety_judge)
graph_builder.add_conditional_edges("get_customer_context", route_after_customer_context)
graph_builder.add_edge("business_rules", "response_writer")
graph_builder.add_edge("human_escalation", "response_writer")
graph_builder.add_conditional_edges("response_writer", route_after_response_writer)
graph_builder.add_edge("knowledge_tool", "response_writer")
graph_builder.add_edge("guardrail", END)

graph = graph_builder.compile()
