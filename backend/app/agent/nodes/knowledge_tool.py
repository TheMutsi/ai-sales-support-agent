from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.state import AgentState


def _run_tool_call(tool, call: dict) -> ToolMessage:
    try:
        return tool.invoke({**call, "type": "tool_call"})
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return ToolMessage(
            content=f"Invalid arguments, the search did not run. {errors}",
            tool_call_id=call["id"],
            status="error",
        )


def knowledge_tool_node(state: AgentState) -> dict:
    tool = make_search_knowledge_base_tool(state["customer_id"])
    last_message = state["messages"][-1]

    return {
        "messages": [_run_tool_call(tool, call) for call in last_message.tool_calls],
        "tool_call_rounds": state.get("tool_call_rounds", 0) + 1,
    }
