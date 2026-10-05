"""Unit tests for the response_writer node: `_build_context_blob` (a pure
function, tested directly) and `response_writer_node` (LLM mocked out, same
pattern as `test_agent_nodes_intent_router.py`)."""

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes import response_writer as response_writer_module
from app.schemas.agent import Intent
from app.schemas.tools import TicketReceipt


class _FakeChatModel:
    """Mimics only the chain `response_writer_node` calls: `.with_retry(...)`
    returns self, `.invoke(...)` hands back a fixed `AIMessage`."""

    def __init__(self, response: AIMessage):
        self._response = response
        self.bound_tools: list | None = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def with_retry(self, **kwargs):
        return self

    def invoke(self, messages):
        return self._response


def test_context_blob_is_empty_note_when_state_has_no_extra_data():
    blob = response_writer_module._build_context_blob({})
    assert blob == "No additional data was retrieved for this request."


def test_context_blob_includes_populated_fields_only():
    ticket = TicketReceipt(ticket_id=uuid.uuid4(), status="open", created_at="2026-01-01T00:00:00")
    state = {"ticket_receipt": ticket}

    blob = response_writer_module._build_context_blob(state)

    assert "Support ticket created" in blob
    assert "Customer account" not in blob


def test_node_returns_the_llms_message_appended_to_state(monkeypatch):
    fake_reply = AIMessage(content="Claro, te cuento...")
    monkeypatch.setattr(
        response_writer_module, "get_chat_model", lambda: _FakeChatModel(fake_reply)
    )

    state = {"messages": [HumanMessage(content="que reportes puedo generar?")]}
    result = response_writer_module.response_writer_node(state)

    assert result == {"messages": [fake_reply]}


@pytest.mark.parametrize(
    "intent",
    [
        Intent.PRODUCT_QUESTION,
        Intent.PRICING_QUESTION,
        Intent.TECHNICAL_SUPPORT,
        Intent.BILLING_QUESTION,
    ],
)
def test_binds_the_knowledge_base_tool_for_rag_eligible_intents(monkeypatch, intent):
    fake_reply = AIMessage(content="It's $49/month.")
    fake_model = _FakeChatModel(fake_reply)
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: fake_model)
    monkeypatch.setattr(
        response_writer_module, "make_search_knowledge_base_tool", lambda customer_id: "fake-tool"
    )

    state = {
        "customer_id": "c-1",
        "intent": intent,
        "messages": [HumanMessage(content="how much is the pro plan?")],
    }
    response_writer_module.response_writer_node(state)

    assert fake_model.bound_tools == ["fake-tool"]


def test_does_not_bind_a_tool_for_non_rag_intents(monkeypatch):
    fake_reply = AIMessage(content="A ticket has been created.")
    fake_model = _FakeChatModel(fake_reply)
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: fake_model)

    state = {
        "customer_id": "c-1",
        "intent": Intent.REFUND_REQUEST,
        "messages": [HumanMessage(content="I want my money back.")],
    }
    response_writer_module.response_writer_node(state)

    assert fake_model.bound_tools is None


class _ScriptedChatModel(_FakeChatModel):
    """Returns the scripted replies in order and records each prompt."""

    def __init__(self, *responses: AIMessage):
        super().__init__(responses[0])
        self._responses = list(responses)
        self.prompts: list[list] = []

    def invoke(self, messages):
        self.prompts.append(messages)
        return self._responses[len(self.prompts) - 1]


def _search_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "search_knowledge_base_tool", "args": {"query": "sso"}, "id": "1"}],
    )


def _run_writer(monkeypatch, model, intent, tool_call_rounds=0) -> dict:
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: model)
    monkeypatch.setattr(
        response_writer_module, "make_search_knowledge_base_tool", lambda customer_id: "fake-tool"
    )
    state = {
        "customer_id": "c-1",
        "intent": intent,
        "tool_call_rounds": tool_call_rounds,
        "messages": [HumanMessage(content="How do I set up SSO?")],
    }
    return response_writer_module.response_writer_node(state)


def test_retries_once_with_a_reminder_when_a_kb_intent_skips_the_search(monkeypatch):
    model = _ScriptedChatModel(AIMessage(content=""), _search_call())

    result = _run_writer(monkeypatch, model, Intent.TECHNICAL_SUPPORT)

    assert result["messages"][0].tool_calls
    assert len(model.prompts) == 2
    assert "Call the search tool now" in model.prompts[1][0].content


def test_keeps_the_retry_reply_even_if_it_still_does_not_search(monkeypatch):
    model = _ScriptedChatModel(AIMessage(content=""), AIMessage(content="No info."))

    result = _run_writer(monkeypatch, model, Intent.PRODUCT_QUESTION)

    assert result["messages"][0].content == "No info."
    assert len(model.prompts) == 2


@pytest.mark.parametrize(
    ("intent", "tool_call_rounds"),
    [
        (Intent.BILLING_QUESTION, 0),  # answerable from customer context
        (Intent.TECHNICAL_SUPPORT, 1),  # already searched this turn
    ],
)
def test_does_not_retry_when_a_search_is_not_required(monkeypatch, intent, tool_call_rounds):
    model = _ScriptedChatModel(AIMessage(content="Here is the answer."))

    _run_writer(monkeypatch, model, intent, tool_call_rounds)

    assert len(model.prompts) == 1
