"""Streaming chat endpoint — wires the compiled agent graph (`app/agent/`) to
HTTP, as Server-Sent Events.

Token deltas are streamed live from `response_writer` as they're generated
(`on_chat_model_stream` events tagged with that node's name). That's a
deliberate bet against the project's own guardrails: `guardrail_node` runs
*after* `response_writer` and occasionally rewrites a BLOCK-severity response
(see `app/guardrails/output_checks.py`) — e.g. the fabricated-ticket-claim
case found live in Stage 7 — so the text already streamed to the client can
turn out to be wrong. Rather than buffering the whole answer server-side
(safe, but loses the instant-typing feel for the vast majority of responses
that guardrails never touch), this streams live and, in the rare case the
final text differs from what was streamed, follows up with a `correction`
event carrying the corrected text. A blocked *input* never reaches
`response_writer` at all (the refusal is attached directly as an `AIMessage`
by `input_guardrail_node`/`safety_judge_node`), so nothing streams for that
path — it's sent as a single `message` event instead.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import graph as agent_graph
from app.schemas.chat import ChatRequest

router = APIRouter()


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_initial_state(request: ChatRequest) -> dict:
    messages = [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in request.messages
    ]
    return {"messages": messages, "customer_id": str(request.customer_id)}


async def stream_chat_turn(chat_graph, request: ChatRequest) -> AsyncIterator[str]:
    conversation_id = request.conversation_id or uuid.uuid4()

    streamed_text = ""
    final_state: dict | None = None

    async for event in chat_graph.astream_events(
        _build_initial_state(request), config={}, version="v2"
    ):
        node = (event.get("metadata") or {}).get("langgraph_node")

        if event["event"] == "on_chat_model_stream" and node == "response_writer":
            delta = event["data"]["chunk"].content
            if delta:
                streamed_text += delta
                yield _format_sse("delta", {"text": delta})

        elif event["event"] == "on_chain_end" and event.get("name") == "LangGraph" and node is None:
            final_state = event["data"]["output"]

    final_text = final_state["messages"][-1].content

    if not streamed_text:
        yield _format_sse("message", {"text": final_text})
    elif final_text != streamed_text:
        yield _format_sse("correction", {"text": final_text})

    yield _format_sse(
        "done",
        {
            "conversation_id": str(conversation_id),
            "intent": final_state.get("intent"),
            "guardrail_flags": final_state.get("guardrail_flags", []),
        },
    )


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(stream_chat_turn(agent_graph, request), media_type="text/event-stream")
