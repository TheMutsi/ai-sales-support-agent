"""Unit tests for the `/api/chat` request contract (`app/schemas/chat.py`)."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest


def test_accepts_a_message_with_its_idempotency_id():
    request = ChatRequest(message="how much is the pro plan?", message_id=uuid.uuid4())

    assert request.message == "how much is the pro plan?"


@pytest.mark.parametrize("body", [{"message": ""}, {"message_id": str(uuid.uuid4())}, {}])
def test_rejects_a_blank_message_or_a_missing_message_id(body):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(body)


def test_the_customer_and_conversation_in_the_body_are_not_part_of_the_request():
    """Both come from the session; a client-supplied one must never reach the graph."""
    request = ChatRequest.model_validate(
        {
            "message": "hi",
            "message_id": str(uuid.uuid4()),
            "customer_id": str(uuid.uuid4()),
            "conversation_id": str(uuid.uuid4()),
        }
    )

    assert not hasattr(request, "customer_id") and not hasattr(request, "conversation_id")
