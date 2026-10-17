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

When the model talks before calling the knowledge-base tool, that text is not the
answer; a `reset` event tells the client to discard it, so `correction` stays a
signal that a guardrail rewrote the final answer.

If the graph run fails, the stream ends with an `error` event (and no
`done`), so clients can tell a failed turn from a dropped connection.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, nullcontext
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from starlette.background import BackgroundTask

from app.agent.graph import graph as agent_graph
from app.agent.names import Node
from app.api.deps import require_customer_session
from app.auth.session import SessionClaims
from app.chat.turns import (
    TurnAction,
    TurnInProgress,
    TurnStart,
    TurnSuperseded,
    abandon_turn,
    begin_turn,
    finish_turn,
)
from app.core.config import get_settings
from app.core.llm import get_chat_model_name
from app.db.models import Conversation
from app.db.session import SessionLocal
from app.schemas.chat import ChatRequest, ChatTurnSummary
from app.schemas.rag import SourceReference

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_initial_state(turn: TurnStart, session: SessionClaims) -> dict:
    messages: list = [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in turn.history
    ]
    messages.append(HumanMessage(content=turn.user_text))
    return {"messages": messages, "customer_id": str(session.customer_id)}


def _collect_sources(messages: list) -> list[SourceReference]:
    """Sources from every knowledge-base search this turn, deduplicated across
    rounds, in the order they were first retrieved. Only this turn's messages
    can carry artifacts: the stored history is plain user/assistant text
    (ADR 0013), so no earlier turn's sources can leak in."""
    sources: dict[str, SourceReference] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.artifact, list):
            for source in message.artifact:
                sources.setdefault(source.source, source)
    return list(sources.values())


def _summarize_turn(final_state: dict, conversation_id: uuid.UUID) -> ChatTurnSummary:
    eligibility_result = final_state.get("eligibility_result")
    ticket_receipt = final_state.get("ticket_receipt")
    # The raw classifier score is an oracle for whoever is probing the input
    # filter (rephrase until it goes up), so production clients never get it;
    # it stays in the traces. Outside production the evaluation suite needs it.
    safety_confidence = (
        None if get_settings().app_env == "production" else final_state.get("safety_confidence")
    )
    return ChatTurnSummary(
        conversation_id=conversation_id,
        intent=final_state.get("intent"),
        guardrail_flags=final_state.get("guardrail_flags", []),
        ticket_created=ticket_receipt is not None,
        escalated=final_state.get("escalated", False),
        upgrade_eligible=eligibility_result.eligible if eligibility_result else None,
        tool_call_rounds=final_state.get("tool_call_rounds", 0),
        input_blocked=final_state.get("input_blocked", False),
        safety_confidence=safety_confidence,
        sources=_collect_sources(final_state.get("messages", [])),
        checkout=final_state.get("checkout_session"),
        ticket_id=ticket_receipt.ticket_id if ticket_receipt else None,
    )


def _build_trace_metadata(session: SessionClaims, conversation_id: uuid.UUID) -> dict:
    settings = get_settings()
    return {
        "customer_id": str(session.customer_id),
        "tenant_id": str(session.tenant_id),
        "identity_level": session.level.value,
        "conversation_id": str(conversation_id),
        "environment": settings.app_env,
        "model": get_chat_model_name(),
        "app_version": settings.app_version,
        # Special keys Langfuse's LangChain integration maps onto the trace's
        # own session/tags fields instead of generic metadata.
        "langfuse_session_id": str(conversation_id),
        "langfuse_tags": ["chat_endpoint"],
    }


class TurnStore(Protocol):
    async def finish(self, content: str) -> None: ...

    async def abandon(self) -> None: ...


async def _abandon_if_unsettled(
    state: "_TurnState", store: TurnStore, conversation_id: uuid.UUID
) -> None:
    if not state.settled:  # skips the DB round trip after every normal turn
        await _abandon_quietly(store, conversation_id)


async def _abandon_quietly(store: TurnStore, conversation_id: uuid.UUID) -> None:
    try:
        await store.abandon()
    except Exception:
        logger.exception("could not free the conversation (conversation_id=%s)", conversation_id)


class _DbTurnStore:
    """Saves the reply or frees the conversation in short DB calls off the event loop."""

    def __init__(self, conversation_id: uuid.UUID, turn: TurnStart):
        self._conversation_id, self._turn = conversation_id, turn

    async def finish(self, content: str) -> None:
        def save() -> None:
            with SessionLocal() as db:
                try:
                    finish_turn(
                        db,
                        conversation_id=self._conversation_id,
                        turn=self._turn,
                        content=content,
                        now=datetime.now(UTC),
                    )
                except TurnSuperseded:
                    logger.warning("late reply dropped (conversation %s)", self._conversation_id)
                except Exception:
                    # Freed here, not left to the caller: after a disconnect this save runs
                    # detached, and nobody else would free the turn if it fails.
                    abandon_turn(db, conversation_id=self._conversation_id, turn=self._turn)
                    raise

        await run_in_threadpool(save)

    async def abandon(self) -> None:
        def free() -> None:
            with SessionLocal() as db:
                abandon_turn(db, conversation_id=self._conversation_id, turn=self._turn)

        await run_in_threadpool(free)


class _TurnState:
    settled = False  # set once the store has been told how the turn ended


async def stream_chat_turn(
    chat_graph,
    session: SessionClaims,
    turn: TurnStart,
    store: TurnStore,
    state: "_TurnState | None" = None,
) -> AsyncIterator[str]:
    """Runs the turn and, however the stream ends (done, error, the client closing it or
    cancelling it), makes sure the conversation isn't left marked busy."""
    state = state or _TurnState()
    try:
        # aclosing: if the client leaves, the graph run and its trace span are closed too,
        # not left suspended until garbage collection.
        async with aclosing(_stream_turn(chat_graph, session, turn, store, state)) as inner:
            async for chunk in inner:
                yield chunk
    finally:
        if not state.settled:
            # Shielded: a cancellation must not interrupt freeing the conversation.
            await asyncio.shield(_abandon_quietly(store, session.conversation_id))
            state.settled = True


async def _stream_turn(
    chat_graph, session: SessionClaims, turn: TurnStart, store: TurnStore, state: _TurnState
) -> AsyncIterator[str]:
    """Drives the graph and translates its event stream into SSE.

    When Langfuse tracing is enabled, the whole turn runs inside one owned
    span (`chat_turn`) so `intent` — unknown until partway through the graph
    run — can be patched onto it directly via `span.update(...)` the moment
    `intent_router` classifies the message. Langfuse's LangChain integration
    isn't a single global env-var switch the way LangSmith's was, so tracing
    is wired per-call here rather than in `app/core/observability.py`."""
    settings = get_settings()
    conversation_id = session.conversation_id
    tracing_enabled = settings.langfuse_tracing_enabled

    span_cm = (
        get_client().start_as_current_observation(
            as_type="span",
            name="chat_turn",
            metadata=_build_trace_metadata(session, conversation_id),
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
                _build_initial_state(turn, session), config=config, version="v2"
            ):
                node = (event.get("metadata") or {}).get("langgraph_node")

                if event["event"] == "on_chat_model_stream" and node == "response_writer":
                    delta = event["data"]["chunk"].content
                    if delta:
                        streamed_text += delta
                        yield _format_sse("delta", {"text": delta})

                elif event["event"] == "on_chain_start" and node == Node.KNOWLEDGE_TOOL:
                    # Whatever streamed so far was the model talking before its
                    # search call ("let me check..."), not the answer. Tell the
                    # client to drop it, so a later `correction` only ever means
                    # a guardrail rewrote the final answer.
                    if streamed_text:
                        streamed_text = ""
                        yield _format_sse("reset", {})

                elif event["event"] == "on_chain_end" and event.get("name") == "intent_router":
                    if tracing_enabled:
                        span.update(metadata={"intent": str(event["data"]["output"]["intent"])})

                elif (
                    event["event"] == "on_chain_end"
                    and event.get("name") == "LangGraph"
                    and node is None
                ):
                    final_state = event["data"]["output"]
        if final_state is None:
            raise RuntimeError("the graph ended without a final state")
    except Exception:
        logger.exception("chat turn failed (conversation_id=%s)", conversation_id)
        await asyncio.shield(_abandon_quietly(store, conversation_id))
        state.settled = True
        yield _format_sse(
            "error",
            {
                "conversation_id": str(conversation_id),
                "message": "The assistant could not complete this response. Please try again.",
            },
        )
        return

    final_text = final_state["messages"][-1].content
    state.settled = True  # from here the store decides the outcome, not the `finally`
    try:
        # Shielded, so a disconnect can't interrupt saving the reply halfway.
        await asyncio.shield(store.finish(final_text))
    except Exception:
        # The client already has its answer, so the stream goes on; but the turn must
        # not stay busy for the next two minutes because the reply wasn't stored.
        logger.exception("could not store the reply (conversation_id=%s)", conversation_id)
        await _abandon_quietly(store, conversation_id)

    if not streamed_text:
        yield _format_sse("message", {"text": final_text})
    elif final_text != streamed_text:
        yield _format_sse("correction", {"text": final_text})

    summary = _summarize_turn(final_state, conversation_id)
    yield _format_sse("done", summary.model_dump(mode="json"))


def _open_turn(session: SessionClaims, request: ChatRequest) -> TurnStart:
    """Checks the session still matches its conversation, then starts the turn (sync)."""
    with SessionLocal() as db:
        conversation = db.get(Conversation, session.conversation_id)
        if (
            conversation is None
            or conversation.tenant_id != session.tenant_id
            or conversation.customer_id != session.customer_id
        ):
            raise LookupError("session does not match its conversation")
        return begin_turn(
            db,
            conversation_id=conversation.id,
            client_message_id=request.message_id,
            content=request.message,
            now=datetime.now(UTC),
        )


async def _replay(reply: str, conversation_id: uuid.UUID) -> AsyncIterator[str]:
    """The stored answer to a message that was already handled, with no model call."""
    yield _format_sse("message", {"text": reply})
    yield _format_sse("done", ChatTurnSummary(conversation_id=conversation_id).model_dump(mode="json"))


@router.post("/chat")
async def chat(
    request: ChatRequest, session: Annotated[SessionClaims, Depends(require_customer_session)]
) -> StreamingResponse:
    # The turn is opened before streaming starts so a refusal can still be a proper
    # HTTP status instead of an event inside a 200 response.
    try:
        turn = await run_in_threadpool(_open_turn, session, request)
    except TurnInProgress:
        raise HTTPException(status_code=409, detail={"code": "turn_in_progress"}) from None
    except LookupError:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_session"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    background = None
    if turn.action is TurnAction.REPLAY:
        stream = _replay(turn.reply or "", session.conversation_id)
    else:
        store = _DbTurnStore(session.conversation_id, turn)
        state = _TurnState()
        stream = stream_chat_turn(agent_graph, session, turn, store, state)
        # If the stream never starts (the client left right after the turn opened) the
        # generator's cleanup never runs; this frees the turn then, and does nothing else.
        background = BackgroundTask(_abandon_if_unsettled, state, store, session.conversation_id)
    return StreamingResponse(stream, media_type="text/event-stream", background=background)
