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

If the graph run fails, the stream ends with an `error` event (and no
`done`), so clients can tell a failed turn from a dropped connection.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import nullcontext
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langfuse import get_client
from langfuse.langchain import CallbackHandler

from app.agent.graph import graph as agent_graph
from app.core.config import get_settings
from app.core.llm import get_chat_model_name
from app.schemas.chat import ChatRequest, ChatTurnSummary

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_initial_state(request: ChatRequest) -> dict:
    messages = [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in request.messages
    ]
    return {"messages": messages, "customer_id": str(request.customer_id)}


def _summarize_turn(final_state: dict, conversation_id: uuid.UUID) -> ChatTurnSummary:
    eligibility_result = final_state.get("eligibility_result")
    return ChatTurnSummary(
        conversation_id=conversation_id,
        intent=final_state.get("intent"),
        guardrail_flags=final_state.get("guardrail_flags", []),
        ticket_created=final_state.get("ticket_receipt") is not None,
        escalated=final_state.get("escalated", False),
        upgrade_eligible=eligibility_result.eligible if eligibility_result else None,
        tool_call_rounds=final_state.get("tool_call_rounds", 0),
    )


def _build_trace_metadata(request: ChatRequest, conversation_id: uuid.UUID) -> dict:
    settings = get_settings()
    return {
        "customer_id": str(request.customer_id),
        "conversation_id": str(conversation_id),
        "environment": settings.app_env,
        "model": get_chat_model_name(),
        "app_version": settings.app_version,
        # Special keys Langfuse's LangChain integration maps onto the trace's
        # own session/tags fields instead of generic metadata.
        "langfuse_session_id": str(conversation_id),
        "langfuse_tags": ["chat_endpoint"],
    }


async def stream_chat_turn(chat_graph, request: ChatRequest) -> AsyncIterator[str]:
    """Drives the graph and translates its event stream into SSE.

    When Langfuse tracing is enabled, the whole turn runs inside one owned
    span (`chat_turn`) so `intent` — unknown until partway through the graph
    run — can be patched onto it directly via `span.update(...)` the moment
    `intent_router` classifies the message. Langfuse's LangChain integration
    isn't a single global env-var switch the way LangSmith's was, so tracing
    is wired per-call here rather than in `app/core/observability.py`."""
    settings = get_settings()
    conversation_id = request.conversation_id or uuid.uuid4()
    tracing_enabled = settings.langfuse_tracing_enabled

    span_cm = (
        get_client().start_as_current_observation(
            as_type="span",
            name="chat_turn",
            metadata=_build_trace_metadata(request, conversation_id),
        )
        if tracing_enabled
        else nullcontext()
    )
    config = {"callbacks": [CallbackHandler()]} if tracing_enabled else {}

    streamed_text = ""
    final_state: dict | None = None

    # The exception is caught outside the span so Langfuse still records the
    # span as failed, while the client gets an explicit `error` event instead
    # of a stream that just stops. Details go to the server log, not the wire.
    try:
        with span_cm as span:
            async for event in chat_graph.astream_events(
                _build_initial_state(request), config=config, version="v2"
            ):
                node = (event.get("metadata") or {}).get("langgraph_node")

                if event["event"] == "on_chat_model_stream" and node == "response_writer":
                    delta = event["data"]["chunk"].content
                    if delta:
                        streamed_text += delta
                        yield _format_sse("delta", {"text": delta})

                elif event["event"] == "on_chain_end" and event.get("name") == "intent_router":
                    if tracing_enabled:
                        span.update(metadata={"intent": str(event["data"]["output"]["intent"])})

                elif (
                    event["event"] == "on_chain_end"
                    and event.get("name") == "LangGraph"
                    and node is None
                ):
                    final_state = event["data"]["output"]
    except Exception:
        logger.exception("chat turn failed (conversation_id=%s)", conversation_id)
        yield _format_sse(
            "error",
            {
                "conversation_id": str(conversation_id),
                "message": "The assistant could not complete this response. Please try again.",
            },
        )
        return

    final_text = final_state["messages"][-1].content

    if not streamed_text:
        yield _format_sse("message", {"text": final_text})
    elif final_text != streamed_text:
        yield _format_sse("correction", {"text": final_text})

    summary = _summarize_turn(final_state, conversation_id)
    yield _format_sse("done", summary.model_dump(mode="json"))


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(stream_chat_turn(agent_graph, request), media_type="text/event-stream")
