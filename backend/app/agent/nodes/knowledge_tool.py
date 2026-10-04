"""Executes whatever `search_knowledge_base_tool` calls `response_writer`'s
LLM requested, and feeds the results back as `ToolMessage`s — the other half
of the LLM↔tool loop `route_after_response_writer` drives.

Arguments come from the model, so they can be invalid (e.g. a `doc_type`
outside the enum). That is the model's mistake, not a system failure: it is
returned to the model as an error `ToolMessage` it can correct on the next
round (still bounded by `_MAX_TOOL_CALL_ROUNDS`), instead of crashing the
whole turn. Anything else the tool raises (database, embeddings) is a real
failure and propagates."""

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.state import AgentState


def _run_tool_call(tool, call: dict) -> ToolMessage:
    try:
        content = tool.invoke(call["args"])
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
    return ToolMessage(content=content, tool_call_id=call["id"])


def knowledge_tool_node(state: AgentState) -> dict:
    tool = make_search_knowledge_base_tool(state["customer_id"])
    last_message = state["messages"][-1]

    return {
        "messages": [_run_tool_call(tool, call) for call in last_message.tool_calls],
        "tool_call_rounds": state.get("tool_call_rounds", 0) + 1,
    }
