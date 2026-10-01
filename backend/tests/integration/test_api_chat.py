"""Integration test for `POST /api/chat` through the real FastAPI app.

The compiled agent graph is swapped for a stub (same approach as
`tests/unit/test_api_chat.py`) so this exercises real HTTP request handling —
validation, routing, the SSE response — without a live LLM call. A full,
real run against the compiled graph + Ollama is verified manually (see the
Stage 8 PR description), per CLAUDE.md's "no fabricated results" rule.
"""

import uuid

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app.api import chat as chat_module
from app.main import app

client = TestClient(app)


class _FakeChunk:
    def __init__(self, content: str):
        self.content = content


class _FakeGraph:
    def __init__(self, events: list[dict]):
        self._events = events

    async def astream_events(self, initial_state, config, version):
        for event in self._events:
            yield event


def test_chat_streams_a_response_over_sse(monkeypatch):
    monkeypatch.setattr(chat_module, "tag_run_intent", lambda *a, **k: None)
    final_state = {
        "messages": [HumanMessage(content="hola"), AIMessage(content="Hola! ¿En qué te ayudo?")],
        "intent": "product_question",
        "guardrail_flags": [],
    }
    monkeypatch.setattr(
        chat_module,
        "agent_graph",
        _FakeGraph(
            [
                {
                    "event": "on_chat_model_stream",
                    "metadata": {"langgraph_node": "response_writer"},
                    "data": {"chunk": _FakeChunk("Hola! ¿En qué te ayudo?")},
                },
                {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "metadata": {},
                    "data": {"output": final_state},
                },
            ]
        ),
    )

    response = client.post(
        "/api/chat",
        json={"customer_id": str(uuid.uuid4()), "messages": [{"role": "user", "content": "hola"}]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in response.text
    assert "event: done" in response.text


def test_chat_rejects_a_request_without_a_trailing_user_message():
    response = client.post(
        "/api/chat",
        json={
            "customer_id": str(uuid.uuid4()),
            "messages": [{"role": "assistant", "content": "hola"}],
        },
    )

    assert response.status_code == 422


def test_chat_rejects_an_invalid_customer_id():
    response = client.post(
        "/api/chat",
        json={"customer_id": "not-a-uuid", "messages": [{"role": "user", "content": "hola"}]},
    )

    assert response.status_code == 422
