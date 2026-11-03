"""The conversation's properties and tags reach the agent as unverified hints and the trace."""

import uuid

from app.agent.nodes.response_writer import _build_context_blob
from app.api.chat import _build_initial_state, _build_trace_metadata
from app.auth.scopes import IdentityLevel
from app.auth.session import SessionClaims
from app.chat.turns import TurnAction, TurnStart


def _session() -> SessionClaims:
    return SessionClaims(
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        customer_id=None,
        level=IdentityLevel.ANONYMOUS,
        order_id=None,
    )


def test_the_hints_go_into_the_initial_state():
    turn = TurnStart(
        TurnAction.RUN, user_text="hi", properties={"device": "iphone"}, tags=["landing-sale"]
    )
    state = _build_initial_state(turn, _session())
    assert state["conversation_properties"] == {"device": "iphone"}
    assert state["conversation_tags"] == ["landing-sale"]


def test_the_writer_sees_them_marked_as_unverified():
    blob = _build_context_blob(
        {"conversation_properties": {"device": "iphone"}, "conversation_tags": ["a", "b"]}
    )
    assert "unverified" in blob
    assert "- device: iphone" in blob
    assert "- tags: a, b" in blob


def test_no_hints_adds_no_section():
    assert "unverified" not in _build_context_blob({})


def test_the_trace_carries_them():
    metadata = _build_trace_metadata(
        _session(), uuid.uuid4(), {"device": "iphone"}, ["landing-sale"]
    )
    assert metadata["property_device"] == "iphone"
    assert metadata["langfuse_tags"] == ["chat_endpoint", "tag:landing-sale"]
