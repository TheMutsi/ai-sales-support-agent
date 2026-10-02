"""Unit test for knowledge_tool_node, with the tool itself mocked out —
exercises the ToolMessage/round-counter bookkeeping, not real retrieval."""

import uuid

from langchain_core.messages import AIMessage

from app.agent.nodes import knowledge_tool as knowledge_tool_module


class _FakeTool:
    def __init__(self, result: str):
        self._result = result
        self.invoked_with: list[dict] = []

    def invoke(self, args):
        self.invoked_with.append(args)
        return self._result


def test_runs_each_requested_call_and_appends_tool_messages(monkeypatch):
    fake_tool = _FakeTool("AcmeFlow Pro costs $49/month.")
    monkeypatch.setattr(
        knowledge_tool_module, "make_search_knowledge_base_tool", lambda customer_id: fake_tool
    )

    ai_message = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_knowledge_base_tool", "args": {"query": "pricing"}, "id": "c1"}
        ],
    )
    state = {"customer_id": str(uuid.uuid4()), "messages": [ai_message]}

    result = knowledge_tool_module.knowledge_tool_node(state)

    assert len(result["messages"]) == 1
    tool_message = result["messages"][0]
    assert tool_message.content == "AcmeFlow Pro costs $49/month."
    assert tool_message.tool_call_id == "c1"
    assert fake_tool.invoked_with == [{"query": "pricing"}]
    assert result["tool_call_rounds"] == 1


def test_increments_the_round_counter_from_its_current_value(monkeypatch):
    fake_tool = _FakeTool("result")
    monkeypatch.setattr(
        knowledge_tool_module, "make_search_knowledge_base_tool", lambda customer_id: fake_tool
    )
    ai_message = AIMessage(
        content="", tool_calls=[{"name": "search_knowledge_base_tool", "args": {}, "id": "c1"}]
    )
    state = {"customer_id": str(uuid.uuid4()), "messages": [ai_message], "tool_call_rounds": 1}

    result = knowledge_tool_module.knowledge_tool_node(state)

    assert result["tool_call_rounds"] == 2
