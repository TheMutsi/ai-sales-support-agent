"""Unit tests for the `/api/chat` request contract (`app/schemas/chat.py`)."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatMessage, ChatRequest


def test_accepts_a_valid_request_ending_in_a_user_message():
    request = ChatRequest(
        messages=[
            ChatMessage(role="assistant", content="Hi, how can I help?"),
            ChatMessage(role="user", content="how much is the pro plan?"),
        ],
    )

    assert request.conversation_id is None
    assert request.messages[-1].role == "user"


def test_rejects_a_request_ending_in_an_assistant_message():
    with pytest.raises(ValidationError, match="last message must be from the user"):
        ChatRequest(
            messages=[ChatMessage(role="assistant", content="Hi")],
        )


def test_rejects_an_empty_message_list():
    with pytest.raises(ValidationError):
        ChatRequest(messages=[])


def test_a_customer_id_in_the_body_is_not_part_of_the_request():
    """The customer comes from the session; a client-supplied one must never reach the graph."""
    request = ChatRequest.model_validate(
        {"customer_id": str(uuid.uuid4()), "messages": [{"role": "user", "content": "hi"}]}
    )

    assert not hasattr(request, "customer_id")


def test_keeps_a_provided_conversation_id():
    conversation_id = uuid.uuid4()
    request = ChatRequest(
        conversation_id=conversation_id,
        messages=[ChatMessage(role="user", content="hi")],
    )

    assert request.conversation_id == conversation_id
