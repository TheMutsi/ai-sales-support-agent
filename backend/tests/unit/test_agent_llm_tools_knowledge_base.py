"""Unit tests for the LLM-facing knowledge-base tool, with retrieval mocked out."""

import uuid

from app.agent.llm_tools import knowledge_base as knowledge_base_module


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
