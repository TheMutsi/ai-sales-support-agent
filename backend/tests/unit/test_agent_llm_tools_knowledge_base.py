import uuid

from app.agent.llm_tools import knowledge_base as knowledge_base_module
from app.schemas.rag import DocType, RetrievedChunk, SourceReference

TENANT_ID = uuid.uuid4()


def test_exposes_only_the_query_to_the_model():
    tool = knowledge_base_module.make_search_knowledge_base_tool(TENANT_ID, None)

    assert set(tool.args) == {"query"}


def test_searches_in_the_bound_tenant_and_plan(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        knowledge_base_module,
        "search_knowledge_base",
        lambda *args, **kwargs: calls.append((args, kwargs)) or [],
    )
    tool = knowledge_base_module.make_search_knowledge_base_tool(TENANT_ID, "pro")

    result = tool.invoke({"query": "how do I set up SSO", "doc_type": "integrations"})

    assert calls == [(("how do I set up SSO",), {"tenant_id": TENANT_ID, "plan_slug": "pro"})]
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
        section="Refunds",
        version=3,
    )


def test_returns_the_text_for_the_model_and_the_sources_as_an_artifact(monkeypatch):
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        knowledge_base_module,
        "search_knowledge_base",
        lambda *a, **k: [_chunk(doc_a, "A", "one"), _chunk(doc_a, "A", "two"), _chunk(doc_b, "B")],
    )
    tool = knowledge_base_module.make_search_knowledge_base_tool(TENANT_ID, None)

    message = tool.invoke(
        {"name": tool.name, "args": {"query": "q"}, "id": "c1", "type": "tool_call"}
    )

    assert message.content == "one\n---\ntwo\n---\ntext"
    assert [s.title for s in message.artifact] == ["A", "B"]
    assert all(isinstance(s, SourceReference) for s in message.artifact)
    assert (message.artifact[0].section, message.artifact[0].version) == ("Refunds", 3)


def test_no_results_means_no_sources(monkeypatch):
    monkeypatch.setattr(knowledge_base_module, "search_knowledge_base", lambda *a, **k: [])
    tool = knowledge_base_module.make_search_knowledge_base_tool(TENANT_ID, None)

    message = tool.invoke({"name": tool.name, "args": {"query": "q"}, "id": "c1", "type": "tool_call"})

    assert message.artifact == []
