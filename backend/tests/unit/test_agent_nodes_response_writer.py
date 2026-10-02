"""Unit tests for the response_writer node: `_build_context_blob` (a pure
function, tested directly) and `response_writer_node` (LLM mocked out, same
pattern as `test_agent_nodes_intent_router.py`)."""

import uuid

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


def test_binds_the_knowledge_base_tool_for_rag_eligible_intents(monkeypatch):
    fake_reply = AIMessage(content="It's $49/month.")
    fake_model = _FakeChatModel(fake_reply)
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: fake_model)
    monkeypatch.setattr(
        response_writer_module, "make_search_knowledge_base_tool", lambda customer_id: "fake-tool"
    )

    state = {
        "customer_id": "c-1",
        "intent": Intent.PRICING_QUESTION,
        "messages": [HumanMessage(content="cuanto sale el plan pro?")],
    }
    response_writer_module.response_writer_node(state)

    assert fake_model.bound_tools == ["fake-tool"]


def test_does_not_bind_a_tool_for_non_rag_intents(monkeypatch):
    fake_reply = AIMessage(content="A ticket has been created.")
    fake_model = _FakeChatModel(fake_reply)
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: fake_model)

    state = {
        "customer_id": "c-1",
        "intent": Intent.BILLING_QUESTION,
        "messages": [HumanMessage(content="why was I charged twice?")],
    }
    response_writer_module.response_writer_node(state)

    assert fake_model.bound_tools is None
