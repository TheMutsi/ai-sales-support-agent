"""Integration test for `POST /api/chat` through the real FastAPI app.

The compiled agent graph is swapped for a stub (same approach as
`tests/unit/test_api_chat.py`) so this exercises real HTTP request handling —
validation, routing, the SSE response — without a live LLM call. A full,
real run against the compiled graph + Ollama is verified manually (see the
Stage 8 PR description), per CLAUDE.md's "no fabricated results" rule.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app.api import chat as chat_module
from app.auth.conversations import resolve_for_login
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.core.config import get_settings
from app.db.models import Customer, Tenant
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


@pytest.fixture
def shop(tenant_wipe):
    """A tenant, a customer and the conversation they are logged in to."""
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        customer = Customer(name="Ana", email="ana@shop.test", tenant_id=tenant.id)
        db.add(customer)
        db.flush()
        conversation = resolve_for_login(
            db, tenant_id=tenant.id, customer_id=customer.id, level=IdentityLevel.STORE_LOGIN,
            conversation_id=None, now=datetime.now(UTC),
        )
        yield {"tenant": tenant, "customer": customer, "conversation": conversation}


def _auth(shop=None, ttl: timedelta = timedelta(hours=1)) -> dict:
    """A session for the shop's conversation, or for made-up ids when `shop` is None."""
    token, _ = issue_session_token(
        tenant_id=shop["tenant"].id if shop else uuid.uuid4(),
        conversation_id=shop["conversation"].id if shop else uuid.uuid4(),
        customer_id=shop["customer"].id if shop else uuid.uuid4(),
        level=IdentityLevel.STORE_LOGIN,
        signing_key=get_settings().session_signing_key,
        ttl=ttl,
    )
    return {"Authorization": f"Bearer {token}"}


def _hi() -> dict:
    return {"message": "hi", "message_id": str(uuid.uuid4())}


class _FakeChunk:
    def __init__(self, content: str):
        self.content = content


class _FakeGraph:
    def __init__(self, events: list[dict]):
        self._events = events
        self.initial_state = None

    async def astream_events(self, initial_state, config, version):
        self.initial_state = initial_state
        for event in self._events:
            yield event


def test_chat_streams_a_response_over_sse(shop, monkeypatch):
    final_state = {
        "messages": [HumanMessage(content="hi"), AIMessage(content="Hi! How can I help?")],
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
                    "data": {"chunk": _FakeChunk("Hi! How can I help?")},
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

    response = client.post("/api/chat", json=_hi(), headers=_auth(shop))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in response.text
    assert "event: done" in response.text


def test_chat_without_a_session_is_rejected_before_reaching_the_graph(monkeypatch):
    graph = _FakeGraph([])
    monkeypatch.setattr(chat_module, "agent_graph", graph)

    response = client.post("/api/chat", json=_hi())

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "missing_session"}
    assert graph.initial_state is None


def test_chat_with_an_expired_session_says_so(monkeypatch):
    monkeypatch.setattr(chat_module, "agent_graph", _FakeGraph([]))

    response = client.post("/api/chat", json=_hi(), headers=_auth(ttl=timedelta(seconds=-120)))

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "session_expired"}


def test_chat_runs_the_graph_as_the_sessions_customer_not_a_body_customer(shop, monkeypatch):
    final_state = {
        "messages": [HumanMessage(content="hi"), AIMessage(content="Hello")],
        "guardrail_flags": [],
    }
    graph = _FakeGraph(
        [
            {
                "event": "on_chain_end",
                "name": "LangGraph",
                "metadata": {},
                "data": {"output": final_state},
            }
        ]
    )
    monkeypatch.setattr(chat_module, "agent_graph", graph)
    victim = uuid.uuid4()

    response = client.post(
        "/api/chat", json={**_hi(), "customer_id": str(victim)}, headers=_auth(shop)
    )

    assert response.status_code == 200
    assert graph.initial_state["customer_id"] == str(shop["customer"].id)


def test_a_malformed_body_without_a_session_still_gets_the_401():
    """Clients key off the auth code, so it must win over body validation."""
    response = client.post("/api/chat", json={"messages": []})

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "missing_session"}
