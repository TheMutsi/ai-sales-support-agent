"""Unit test for knowledge_tool_node, with the tool itself mocked out —
exercises the ToolMessage/round-counter bookkeeping, not real retrieval."""

import uuid

import pytest
from langchain_core.messages import AIMessage

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
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


def test_invalid_arguments_become_an_error_tool_message_instead_of_raising(monkeypatch):
    """Regression for a crash found by the evaluation suite: the model asked
    for `doc_type="pricing"`, which is not a `DocType`, and the validation
    error escaped the graph and cut the HTTP stream. The real tool is used so
    its own argument validation runs; retrieval must never be reached."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("retrieval must not run with invalid arguments")

    monkeypatch.setattr(
        "app.agent.llm_tools.knowledge_base.search_knowledge_base", fail_if_called
    )
    monkeypatch.setattr(
        knowledge_tool_module, "make_search_knowledge_base_tool", make_search_knowledge_base_tool
    )
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_knowledge_base_tool",
                "args": {"query": "pro plan price", "doc_type": "pricing"},
                "id": "c1",
            }
        ],
    )
    state = {"customer_id": str(uuid.uuid4()), "messages": [ai_message]}

    result = knowledge_tool_module.knowledge_tool_node(state)

    tool_message = result["messages"][0]
    assert tool_message.status == "error"
    assert tool_message.tool_call_id == "c1"
    assert "doc_type" in tool_message.content
    assert result["tool_call_rounds"] == 1


def test_other_tool_failures_still_propagate(monkeypatch):
    class _BrokenTool:
        def invoke(self, args):
            raise ConnectionError("database unavailable")

    monkeypatch.setattr(
        knowledge_tool_module, "make_search_knowledge_base_tool", lambda customer_id: _BrokenTool()
    )
    ai_message = AIMessage(
        content="", tool_calls=[{"name": "search_knowledge_base_tool", "args": {}, "id": "c1"}]
    )
    state = {"customer_id": str(uuid.uuid4()), "messages": [ai_message]}

    with pytest.raises(ConnectionError):
        knowledge_tool_module.knowledge_tool_node(state)
