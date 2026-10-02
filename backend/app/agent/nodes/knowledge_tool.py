"""Executes whatever `search_knowledge_base_tool` calls `response_writer`'s
LLM requested, and feeds the results back as `ToolMessage`s — the other half
of the LLM↔tool loop `route_after_response_writer` drives."""

from langchain_core.messages import ToolMessage

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.state import AgentState


def knowledge_tool_node(state: AgentState) -> dict:
    tool = make_search_knowledge_base_tool(state["customer_id"])
    last_message = state["messages"][-1]

    tool_messages = [
        ToolMessage(content=tool.invoke(call["args"]), tool_call_id=call["id"])
        for call in last_message.tool_calls
    ]
    return {
        "messages": tool_messages,
        "tool_call_rounds": state.get("tool_call_rounds", 0) + 1,
    }
