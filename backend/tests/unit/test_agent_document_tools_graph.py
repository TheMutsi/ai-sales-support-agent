import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.agent.llm_tools import documents as documents_module
from app.agent.names import Node
from app.agent.nodes import response_writer as response_writer_module
from app.agent.nodes.guardrail import guardrail_node
from app.agent.nodes.knowledge_tool import knowledge_tool_node
from app.agent.nodes.response_writer import response_writer_node
from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.routing import route_after_response_writer
from app.agent.state import AgentState
from app.guardrails.output_checks import check_system_prompt_leak
from app.schemas.agent import Intent
from app.schemas.guardrails import OutputCheckContext
from app.schemas.rag import DocType, DocumentMapEntry, OpenDocumentsResult, OpenedDocument

TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()
TERMS_ID = uuid.uuid4()
PRIVACY_ID = uuid.uuid4()
FOREIGN_ID = uuid.uuid4()
TERMS_TEXT = "The Customer may cancel at any time with thirty days notice."


def _entry(document_id, title) -> DocumentMapEntry:
    return DocumentMapEntry(
        document_id=document_id, title=title, when_to_use=f"About {title}", estimated_tokens=100
    )


STORE = {
    TENANT_ID: {
        TERMS_ID: OpenedDocument(
            document_id=TERMS_ID, title="Terms", doc_type=DocType.POLICY, source="Terms.md", version=2, estimated_tokens=100, text=TERMS_TEXT
        ),
        PRIVACY_ID: OpenedDocument(
            document_id=PRIVACY_ID, title="Privacy", doc_type=DocType.POLICY, source="Privacy.md", version=1, estimated_tokens=100, text="We keep data."
        ),
    },
    OTHER_TENANT_ID: {
        FOREIGN_ID: OpenedDocument(
            document_id=FOREIGN_ID, title="Other", doc_type=DocType.POLICY, source="Other.md", version=1, estimated_tokens=10, text="secret"
        )
    },
}


class _ScriptedModel:
    def __init__(self, *responses: AIMessage):
        self._responses = list(responses)
        self.prompts: list[list] = []

    def bind_tools(self, tools):
        return self

    def with_retry(self, **kwargs):
        return self

    def invoke(self, messages):
        self.prompts.append(messages)
        return self._responses[min(len(self.prompts), len(self._responses)) - 1]


def _open_call(*document_ids, call_id="c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "open_documents_tool",
                "args": {"document_ids": [str(document_id) for document_id in document_ids]},
                "id": call_id,
            }
        ],
    )


@pytest.fixture(autouse=True)
def _wired(monkeypatch):
    def fake_open_documents(tenant_id, plan_slug, document_ids):
        owned = STORE.get(tenant_id, {})
        result = OpenDocumentsResult()
        for document_id in document_ids:
            if document_id in owned:
                result.documents.append(owned[document_id])
            else:
                result.not_found.append(document_id)
        return result

    monkeypatch.setattr(documents_module, "open_documents", fake_open_documents)
    monkeypatch.setattr(
        response_writer_module,
        "get_document_map",
        lambda tenant_id, plan_slug: (_entry(TERMS_ID, "Terms"), _entry(PRIVACY_ID, "Privacy")),
    )


def _graph():
    builder = StateGraph(AgentState)
    builder.add_node(Node.RESPONSE_WRITER, response_writer_node)
    builder.add_node(Node.KNOWLEDGE_TOOL, knowledge_tool_node)
    builder.add_node(Node.GUARDRAIL, guardrail_node)
    builder.add_edge(START, Node.RESPONSE_WRITER)
    builder.add_conditional_edges(Node.RESPONSE_WRITER, route_after_response_writer)
    builder.add_edge(Node.KNOWLEDGE_TOOL, Node.RESPONSE_WRITER)
    builder.add_edge(Node.GUARDRAIL, END)
    return builder.compile()


def _run(monkeypatch, model, tenant_id=TENANT_ID) -> dict:
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: model)
    return _graph().invoke(
        {
            "customer_id": None,
            "tenant_id": str(tenant_id),
            "intent": Intent.PRODUCT_QUESTION,
            "messages": [HumanMessage(content="What are the terms and conditions?")],
        }
    )


def _tool_messages(final_state) -> list[ToolMessage]:
    return [m for m in final_state["messages"] if isinstance(m, ToolMessage)]


def test_the_prompt_lists_the_document_map_after_the_instructions(monkeypatch):
    model = _ScriptedModel(_open_call(TERMS_ID), AIMessage(content="Here are the terms."))

    _run(monkeypatch, model)

    prompt = model.prompts[0][0].content
    assert str(TERMS_ID) in prompt and "About Privacy" in prompt
    assert prompt.index("Context:") < prompt.index("<document_map>")
    assert prompt.split("\n\n")[0] == RESPONSE_WRITER_SYSTEM_PROMPT.split("\n\n")[0]


def test_answering_without_opening_any_document(monkeypatch):
    model = _ScriptedModel(AIMessage(content="No tool needed."))

    final_state = _run(monkeypatch, model)

    assert _tool_messages(final_state) == []
    assert final_state.get("tool_call_rounds", 0) == 0


def test_opening_one_document_returns_its_text_and_a_versioned_source(monkeypatch):
    model = _ScriptedModel(_open_call(TERMS_ID), AIMessage(content=f'The terms say: "{TERMS_TEXT}"'))

    final_state = _run(monkeypatch, model)

    (tool_message,) = _tool_messages(final_state)
    assert TERMS_TEXT in tool_message.content
    assert [(s.title, s.version) for s in tool_message.artifact] == [("Terms", 2)]
    assert final_state["tool_call_rounds"] == 1


def test_opening_two_documents_cites_both(monkeypatch):
    model = _ScriptedModel(_open_call(TERMS_ID, PRIVACY_ID), AIMessage(content="Both read."))

    final_state = _run(monkeypatch, model)

    (tool_message,) = _tool_messages(final_state)
    assert [(s.title, s.version) for s in tool_message.artifact] == [("Terms", 2), ("Privacy", 1)]


def test_another_tenants_document_is_not_found_and_not_shown(monkeypatch):
    model = _ScriptedModel(_open_call(FOREIGN_ID), AIMessage(content="I could not open it."))

    final_state = _run(monkeypatch, model)

    (tool_message,) = _tool_messages(final_state)
    assert "secret" not in tool_message.content
    assert str(FOREIGN_ID) in tool_message.content and "No document available" in tool_message.content
    assert tool_message.artifact == []


def test_a_malformed_id_goes_back_to_the_model_as_an_error(monkeypatch):
    bad_call = AIMessage(
        content="",
        tool_calls=[{"name": "open_documents_tool", "args": {"document_ids": ["not-an-id"]}, "id": "c1"}],
    )
    model = _ScriptedModel(bad_call, AIMessage(content="Sorry."))

    final_state = _run(monkeypatch, model)

    (tool_message,) = _tool_messages(final_state)
    assert tool_message.status == "error"


def test_the_round_limit_is_shared_with_the_search_tool(monkeypatch):
    model = _ScriptedModel(_open_call(TERMS_ID, call_id="c1"), _open_call(PRIVACY_ID, call_id="c2"), _open_call(TERMS_ID, call_id="c3"))

    final_state = _run(monkeypatch, model)

    assert final_state["tool_call_rounds"] == 2
    assert len(_tool_messages(final_state)) == 2
    assert len(model.prompts) == 3


def test_quoting_an_opened_document_is_not_a_system_prompt_leak(monkeypatch):
    model = _ScriptedModel(_open_call(TERMS_ID), AIMessage(content=f'The terms say: "{TERMS_TEXT}"'))

    final_state = _run(monkeypatch, model)

    reply = final_state["messages"][-1]
    assert reply.content == f'The terms say: "{TERMS_TEXT}"'
    assert "guardrail_flags" not in final_state or final_state["guardrail_flags"] == []
    context = OutputCheckContext(protected_prompt=RESPONSE_WRITER_SYSTEM_PROMPT)
    assert check_system_prompt_leak(context, reply.content) is None


def test_a_document_too_long_is_listed_by_its_sections_and_not_cited(monkeypatch):
    long_id = uuid.uuid4()
    STORE[TENANT_ID][long_id] = OpenedDocument(
        document_id=long_id,
        title="Long",
        doc_type=DocType.POLICY,
        source="Long.md",
        version=1,
        estimated_tokens=9000,
        section_titles=["Fees", "Liability"],
        omitted_reason="document_too_long",
    )
    try:
        model = _ScriptedModel(_open_call(long_id), AIMessage(content="See the sections."))
        final_state = _run(monkeypatch, model)
    finally:
        del STORE[TENANT_ID][long_id]

    (tool_message,) = _tool_messages(final_state)
    assert "document_too_long" in tool_message.content and "Fees, Liability" in tool_message.content
    assert tool_message.artifact == []
