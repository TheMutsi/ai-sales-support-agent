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
from app.chat.turns import MessageKind, begin_turn, finish_turn
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Message, Tenant
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


def test_a_completed_turn_leaves_the_conversation_free_and_its_reply_stored(shop, monkeypatch):
    """The cleanup that runs after the response must be a no-op once the turn finished."""
    final_state = {
        "messages": [HumanMessage(content="hi"), AIMessage(content="Hello there")],
        "guardrail_flags": [],
    }
    end = {"event": "on_chain_end", "name": "LangGraph", "metadata": {}, "data": {"output": final_state}}
    monkeypatch.setattr(chat_module, "agent_graph", _FakeGraph([end]))

    assert client.post("/api/chat", json=_hi(), headers=_auth(shop)).status_code == 200

    with SessionLocal() as db:
        conversation = db.get(Conversation, shop["conversation"].id)
        assert conversation.turn_started_at is None and conversation.turn_id is None
        replies = db.query(Message).filter_by(conversation_id=conversation.id, role="assistant")
        assert [m.content for m in replies] == ["Hello there"]


@pytest.mark.asyncio
async def test_a_store_whose_save_fails_frees_the_conversation_by_itself(shop, monkeypatch):
    """Not left to the caller: after a disconnect the save runs detached, and if it then
    fails nobody else would free the turn."""
    with SessionLocal() as db:
        turn = begin_turn(
            db, conversation_id=shop["conversation"].id, client_message_id=uuid.uuid4(),
            content="hi", now=datetime.now(UTC),
        )

    def broken(*args, **kwargs):
        raise RuntimeError("db down while saving")

    monkeypatch.setattr(chat_module, "finish_turn", broken)
    store = chat_module._DbTurnStore(shop["conversation"].id, turn)

    with pytest.raises(RuntimeError):
        await store.finish("Hello")

    with SessionLocal() as db:
        assert db.get(Conversation, shop["conversation"].id).turn_id is None


def test_reusing_a_message_id_with_different_text_is_refused(shop):
    message_id = str(uuid.uuid4())
    with SessionLocal() as db:
        first = begin_turn(
            db,
            conversation_id=shop["conversation"].id,
            client_message_id=uuid.UUID(message_id),
            content="original",
            now=datetime.now(UTC),
        )
        finish_turn(
            db,
            conversation_id=shop["conversation"].id,
            turn=first,
            content="answer",
            now=datetime.now(UTC),
        )

    response = client.post(
        "/api/chat", json={"message": "different", "message_id": message_id}, headers=_auth(shop)
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "message_id_reused"


def _store(shop, user_text="hi", reply="Hello!"):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        turn = begin_turn(
            db,
            conversation_id=shop["conversation"].id,
            client_message_id=uuid.uuid4(),
            content=user_text,
            now=now,
        )
        finish_turn(db, conversation_id=shop["conversation"].id, turn=turn, content=reply, now=now)


def test_the_session_can_read_its_conversations_messages_in_order(shop):
    _store(shop, "hi", "Hello!")
    _store(shop, "plans?", "Three plans.")

    response = client.get(
        f"/api/conversations/{shop['conversation'].id}/messages", headers=_auth(shop)
    )

    assert response.status_code == 200
    body = response.json()
    assert [(m["seq"], m["role"], m["content"]) for m in body["messages"]] == [
        (1, "user", "hi"),
        (2, "assistant", "Hello!"),
        (3, "user", "plans?"),
        (4, "assistant", "Three plans."),
    ]
    assert "created_at" in body["messages"][0]


def test_a_new_conversation_has_no_messages(shop):
    response = client.get(
        f"/api/conversations/{shop['conversation'].id}/messages", headers=_auth(shop)
    )

    assert response.status_code == 200 and response.json() == {"messages": []}


def test_messages_need_a_session():
    response = client.get(f"/api/conversations/{uuid.uuid4()}/messages")

    assert response.status_code == 401


def test_another_conversations_messages_are_not_readable_with_this_session(shop):
    """Same answer as for a conversation that does not exist: no way to probe ids."""
    other = uuid.uuid4()

    response = client.get(f"/api/conversations/{other}/messages", headers=_auth(shop))

    assert response.status_code == 404


def test_the_messages_endpoint_says_which_message_is_a_form(shop):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        turn = begin_turn(
            db,
            conversation_id=shop["conversation"].id,
            client_message_id=uuid.uuid4(),
            content="my invoice?",
            now=now,
        )
        finish_turn(
            db,
            conversation_id=shop["conversation"].id,
            turn=turn,
            content="I need to verify it is you.",
            now=now,
            kind=MessageKind.IDENTITY_REQUEST,
        )

    response = client.get(
        f"/api/conversations/{shop['conversation'].id}/messages", headers=_auth(shop)
    )

    assert [m["kind"] for m in response.json()["messages"]] == ["text", "identity_request"]


class _RecordingGraph:
    """Ends each run with a plain answer and remembers what it was started with."""

    def __init__(self):
        self.runs: list[dict] = []

    async def astream_events(self, initial_state, config, version):
        self.runs.append(initial_state)
        answer = AIMessage(content="Your next invoice is on the 3rd.")
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "metadata": {},
            "data": {"output": {"messages": [answer]}},
        }


def _ask_and_get_asked_for_identity(shop, text="my invoice?"):
    message_id = uuid.uuid4()
    now = datetime.now(UTC)
    with SessionLocal() as db:
        turn = begin_turn(
            db,
            conversation_id=shop["conversation"].id,
            client_message_id=message_id,
            content=text,
            now=now,
        )
        finish_turn(
            db,
            conversation_id=shop["conversation"].id,
            turn=turn,
            content="Please verify.",
            now=now,
            kind=MessageKind.IDENTITY_REQUEST,
        )
    return message_id


def test_resuming_answers_the_message_the_visitor_was_asked_to_identify_for(shop, monkeypatch):
    graph = _RecordingGraph()
    monkeypatch.setattr(chat_module, "agent_graph", graph)
    _ask_and_get_asked_for_identity(shop, "when is my next invoice?")

    response = client.post("/api/chat/resume", headers=_auth(shop))

    assert response.status_code == 200 and "event: done" in response.text
    assert graph.runs[0]["messages"][-1].content == "when is my next invoice?"
    stored = client.get(
        f"/api/conversations/{shop['conversation'].id}/messages", headers=_auth(shop)
    ).json()["messages"]
    assert [(m["role"], m["kind"]) for m in stored] == [
        ("user", "text"),
        ("assistant", "identity_request"),
        ("assistant", "text"),
    ]


def test_resuming_twice_does_not_answer_twice(shop, monkeypatch):
    graph = _RecordingGraph()
    monkeypatch.setattr(chat_module, "agent_graph", graph)
    _ask_and_get_asked_for_identity(shop)

    first = client.post("/api/chat/resume", headers=_auth(shop))
    second = client.post("/api/chat/resume", headers=_auth(shop))

    assert first.status_code == 200
    assert second.status_code == 404
    assert len(graph.runs) == 1


def test_there_is_nothing_to_resume_in_a_conversation_that_asked_for_nothing(shop):
    response = client.post("/api/chat/resume", headers=_auth(shop))

    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "nothing_to_resume"}


def test_resuming_needs_a_session():
    assert client.post("/api/chat/resume").status_code == 401
