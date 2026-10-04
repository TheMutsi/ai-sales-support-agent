"""Minimal client for `POST /api/chat`: sends one case's conversation and
folds the Server-Sent Events response into a `ChatTurn`.

Parsing is split into two pure steps (`iter_sse_events`, then
`collect_chat_turn`) so the wire format is unit-tested without a server.
"""

import json
import uuid
from collections.abc import Iterable, Iterator

import httpx

from app.schemas.chat import ChatTurnSummary

from .schemas import ChatTurn, EvalCase

_REQUEST_TIMEOUT_SECONDS = 120.0


def iter_sse_events(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """Parses a Server-Sent Events stream into `(event_type, data)` pairs.
    Supports the subset `/api/chat` emits: one `event:` and one `data:` line
    per event."""
    event_type: str | None = None
    for line in lines:
        if line.startswith("event: "):
            event_type = line.removeprefix("event: ")
        elif line.startswith("data: ") and event_type is not None:
            yield event_type, json.loads(line.removeprefix("data: "))
            event_type = None


def collect_chat_turn(events: Iterable[tuple[str, dict]]) -> ChatTurn:
    """Folds the events of one turn into its final result. A `message` or
    `correction` event carries the authoritative full text and replaces
    whatever was streamed as `delta`s; an `error` event fails the turn."""
    streamed_text = ""
    final_text: str | None = None
    summary: ChatTurnSummary | None = None
    for event_type, data in events:
        if event_type == "delta":
            streamed_text += data["text"]
        elif event_type in ("message", "correction"):
            final_text = data["text"]
        elif event_type == "done":
            summary = ChatTurnSummary.model_validate(data)
        elif event_type == "error":
            raise RuntimeError(f"server reported an error: {data.get('message')}")

    if summary is None:
        raise RuntimeError("stream ended without a 'done' event")
    return ChatTurn(
        response_text=final_text if final_text is not None else streamed_text,
        summary=summary,
    )


def run_chat_turn(
    client: httpx.Client, base_url: str, customer_id: uuid.UUID, case: EvalCase
) -> ChatTurn:
    payload = {
        "customer_id": str(customer_id),
        "messages": [message.model_dump() for message in case.messages],
    }
    with client.stream(
        "POST", f"{base_url}/api/chat", json=payload, timeout=_REQUEST_TIMEOUT_SECONDS
    ) as response:
        response.raise_for_status()
        return collect_chat_turn(iter_sse_events(response.iter_lines()))
