import uuid

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.llm_tools.plan_scope import resolve_plan_slug
from app.agent.state import AgentState

SEARCH_TOOL_NAME = "search_knowledge_base_tool"


def _error_message(call: dict, content: str) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call["id"], status="error")


def _run_tool_call(tools: dict, call: dict) -> ToolMessage:
    tool = tools.get(call["name"])
    if tool is None:
        return _error_message(call, f"Unknown tool {call['name']}. The tool did not run.")
    try:
        return tool.invoke({**call, "type": "tool_call"})
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return _error_message(call, f"Invalid arguments, the tool did not run. {errors}")


def knowledge_tool_node(state: AgentState) -> dict:
    tenant_id = uuid.UUID(state["tenant_id"])
    plan_slug = resolve_plan_slug(state)
    tools = {
        SEARCH_TOOL_NAME: make_search_knowledge_base_tool(tenant_id, plan_slug),
    }
    last_message = state["messages"][-1]

    return {
        "messages": [_run_tool_call(tools, call) for call in last_message.tool_calls],
        "tool_call_rounds": state.get("tool_call_rounds", 0) + 1,
    }
