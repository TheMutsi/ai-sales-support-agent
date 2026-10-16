"""Unit tests for the LLM-facing knowledge-base tool, with retrieval mocked out."""

import uuid

from app.agent.llm_tools import knowledge_base as knowledge_base_module
from app.schemas.rag import DocType, RetrievedChunk, SourceReference


def test_exposes_only_the_query_to_the_model():
    """Regression: with a `doc_type` argument, the model picked the wrong
    category and the filter hid the document holding the answer."""
    tool = knowledge_base_module.make_search_knowledge_base_tool(uuid.uuid4())

    assert set(tool.args) == {"query"}


def test_searches_unfiltered_for_the_bound_customer(monkeypatch):
    customer_id = uuid.uuid4()
    calls: list[tuple] = []
    monkeypatch.setattr(
        knowledge_base_module,
        "search_knowledge_base",
        lambda *args, **kwargs: calls.append((args, kwargs)) or [],
    )
    tool = knowledge_base_module.make_search_knowledge_base_tool(customer_id)

    # A stale `doc_type` from the model is dropped by the args schema.
    result = tool.invoke({"query": "how do I set up SSO", "doc_type": "integrations"})

    assert calls == [((customer_id, "how do I set up SSO"), {})]
    assert result == "No relevant knowledge base results found."


def _chunk(document_id, title, content="text") -> RetrievedChunk:
    return RetrievedChunk(
        document_id=document_id,
        chunk_id=uuid.uuid4(),
        content=content,
        score=0.9,
        doc_type=DocType.POLICY,
        document_title=title,
        source=f"{title}.md",
    )


def test_returns_the_text_for_the_model_and_the_sources_as_an_artifact(monkeypatch):
    """The model sees only the chunk text; the sources travel beside it as the
    ToolMessage artifact, so the client can cite them without the model being
    asked to (and able to misquote) them."""
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        knowledge_base_module,
        "search_knowledge_base",
        lambda *a, **k: [_chunk(doc_a, "A", "one"), _chunk(doc_a, "A", "two"), _chunk(doc_b, "B")],
    )
    tool = knowledge_base_module.make_search_knowledge_base_tool(uuid.uuid4())

    message = tool.invoke(
        {"name": tool.name, "args": {"query": "q"}, "id": "c1", "type": "tool_call"}
    )

    assert message.content == "one\n---\ntwo\n---\ntext"
    # Two chunks of document A collapse into one citation.
    assert [s.title for s in message.artifact] == ["A", "B"]
    assert all(isinstance(s, SourceReference) for s in message.artifact)


def test_no_results_means_no_sources(monkeypatch):
    monkeypatch.setattr(knowledge_base_module, "search_knowledge_base", lambda *a, **k: [])
    tool = knowledge_base_module.make_search_knowledge_base_tool(uuid.uuid4())

    message = tool.invoke({"name": tool.name, "args": {"query": "q"}, "id": "c1", "type": "tool_call"})

    assert message.artifact == []
