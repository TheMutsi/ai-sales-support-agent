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
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, nullcontext
from dataclasses import replace
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
from app.api.deps import require_session
from app.api.origins import origin_guard_for_session
from app.api.rate_limit import limit_by_conversation
from app.auth.scopes import scopes_for
from app.auth.session import SessionClaims
from app.cards import cards_for
from app.chat.actions import latest_cards, offered_card
from app.chat.turns import (
    KEEP,
    HandoffStatus,
    Keep,
    MessageIdReused,
    MessageKind,
    TurnAction,
    TurnInProgress,
    TurnStart,
    TurnSuperseded,
    abandon_turn,
    begin_turn,
    finish_turn,
    list_messages,
    pending_message,
)
from app.core.config import get_settings
from app.core.llm import get_chat_model_name
from app.core.tenant_config import tenant_configs
from app.db.models import Conversation, Message
from app.db.session import SessionLocal
from app.schemas.cards import Card
from app.schemas.chat import (
    ActionInput,
    ChatRequest,
    ChatTurnSummary,
    MessageList,
    StoredMessage,
)
from app.schemas.orders import PendingReturn
from app.schemas.rag import SourceReference

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_initial_state(
    turn: TurnStart, session: SessionClaims, scope_overrides: dict | None = None
) -> dict:
    messages: list = [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in turn.history
    ]
    messages.append(HumanMessage(content=turn.user_text))
    return {
        "messages": messages,
        "customer_id": str(session.customer_id) if session.customer_id else None,
        "tenant_id": str(session.tenant_id),
        "order_id": session.order_id,
        "pending_return": turn.pending_return,
        "action": turn.click,
        "action_order_id": turn.click_order_id,
        "scopes": sorted(s.value for s in scopes_for(session.level, scope_overrides)),
        "scope_overrides": scope_overrides,
    }


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
        identity_required=final_state.get("identity_required", False),
        identity_methods=final_state.get("identity_methods", []),
        cards=cards_for(final_state),
    )


def _build_trace_metadata(session: SessionClaims, conversation_id: uuid.UUID) -> dict:
    settings = get_settings()
    return {
        "customer_id": str(session.customer_id) if session.customer_id else None,
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
    async def finish(
        self,
        content: str,
        kind: MessageKind = MessageKind.TEXT,
        escalation_ticket_id: uuid.UUID | None = None,
        pending_return: PendingReturn | None | Keep = KEEP,
        cards: list[Card] | None = None,
    ) -> None: ...

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

    async def finish(
        self,
        content: str,
        kind: MessageKind = MessageKind.TEXT,
        escalation_ticket_id: uuid.UUID | None = None,
        pending_return: PendingReturn | None | Keep = KEEP,
        cards: list[Card] | None = None,
    ) -> None:
        def save() -> None:
            with SessionLocal() as db:
                try:
                    finish_turn(
                        db,
                        conversation_id=self._conversation_id,
                        turn=self._turn,
                        content=content,
                        now=datetime.now(UTC),
                        kind=kind,
                        escalation_ticket_id=escalation_ticket_id,
                        pending_return=pending_return,
                        cards=cards,
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
    scope_overrides: dict | None = None,
) -> AsyncIterator[str]:
    """Runs the turn and, however the stream ends (done, error, the client closing it or
    cancelling it), makes sure the conversation isn't left marked busy."""
    state = state or _TurnState()
    try:
        # aclosing: if the client leaves, the graph run and its trace span are closed too,
        # not left suspended until garbage collection.
        async with aclosing(
            _stream_turn(chat_graph, session, turn, store, state, scope_overrides)
        ) as inner:
            async for chunk in inner:
                yield chunk
    finally:
        if not state.settled:
            # Shielded: a cancellation must not interrupt freeing the conversation.
            await asyncio.shield(_abandon_quietly(store, session.conversation_id))
            state.settled = True


async def _stream_turn(
    chat_graph,
    session: SessionClaims,
    turn: TurnStart,
    store: TurnStore,
    state: _TurnState,
    scope_overrides: dict | None = None,
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
                _build_initial_state(turn, session, scope_overrides), config=config, version="v2"
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
    kind = MessageKind.IDENTITY_REQUEST if final_state.get("identity_required") else MessageKind.TEXT
    try:
        # Shielded, so a disconnect can't interrupt saving the reply halfway.
        receipt = final_state.get("ticket_receipt")
        await asyncio.shield(
            store.finish(
                final_text,
                kind,
                escalation_ticket_id=receipt.ticket_id if receipt else None,
                # Absent means "this run did not touch it", never "clear it".
                pending_return=final_state.get("pending_return", KEEP),
                cards=cards_for(final_state),
            )
        )
    except Exception:
        # The client already has its answer, so the stream goes on; but the turn must
        # not stay busy for the next two minutes because the reply wasn't stored.
        logger.exception("could not store the reply (conversation_id=%s)", conversation_id)
        await _abandon_quietly(store, conversation_id)

    if not streamed_text:
        # A reply no model wrote (a fixed question, a refusal) is still shown as it is typed,
        # word by word, like one the model streams; the reply was stored before this.
        async for chunk in _typed(final_text):
            yield _format_sse("delta", {"text": chunk})
    elif final_text != streamed_text:
        yield _format_sse("correction", {"text": final_text})

    summary = _summarize_turn(final_state, conversation_id)
    yield _format_sse("done", summary.model_dump(mode="json"))


class ActionNotOffered(Exception):
    """A click on a button the latest reply did not offer. Carries the cards that were."""

    def __init__(self, cards: list[Card]):
        self.cards = cards


def _text_of(db, conversation_id: uuid.UUID, request: ChatRequest) -> str:
    """What the message says in the conversation. A click says what its card says (the client
    never supplies it), and a retry of a click that was already stored says what was stored."""
    entry = request.input
    if not isinstance(entry, ActionInput):
        return entry.message
    stored = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, client_message_id=request.message_id)
        .one_or_none()
    )
    if stored is not None:
        return stored.content
    cards = latest_cards(db, conversation_id)
    card = offered_card(cards, entry.action, entry.order_id)
    if card is None:
        raise ActionNotOffered(cards)
    return card.message


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
        turn = begin_turn(
            db,
            conversation_id=conversation.id,
            client_message_id=request.message_id,
            content=_text_of(db, conversation.id, request),
            now=datetime.now(UTC),
        )
        entry = request.input
        if isinstance(entry, ActionInput) and turn.action is TurnAction.RUN:
            turn = replace(turn, click=entry.action, click_order_id=entry.order_id)
        return turn


def _scope_overrides(session: SessionClaims) -> dict | None:
    """The tenant's per-level scope overrides: what this session may do depends on them. Read
    from the configuration cache, so a change in the back office applies at once on the instance
    that made it and within the cache's TTL on the others."""
    tenant = tenant_configs.get(session.tenant_id)
    return tenant.scope_overrides if tenant is not None else None


_NOT_UNDERSTOOD = "Sorry, I didn't understand that. Could you ask it another way?"

# How long between the words of a reply nobody generated; about the pace of a fast typist.
_TYPING_DELAY_SECONDS = 0.03


async def _typed(text: str) -> AsyncIterator[str]:
    """`text` a word at a time, with a short pause between words."""
    for index, word in enumerate(re.findall(r"\S+\s*|\s+", text)):
        if index:
            await asyncio.sleep(_TYPING_DELAY_SECONDS)
        yield word


async def _replay(
    reply: str, conversation_id: uuid.UUID, cards: list | None = None
) -> AsyncIterator[str]:
    """The stored answer to a message that was already handled, with no model call: its cards
    too, so a retried request shows what the first one did."""
    yield _format_sse("message", {"text": reply})
    summary = ChatTurnSummary(conversation_id=conversation_id, cards=cards or [])
    yield _format_sse("done", summary.model_dump(mode="json"))


async def _handed_off(conversation_id: uuid.UUID, handoff: HandoffStatus) -> AsyncIterator[str]:
    """The message is stored; a person has the conversation, so there is no answer to stream."""
    summary = ChatTurnSummary(conversation_id=conversation_id, handoff=handoff.value)
    yield _format_sse("done", summary.model_dump(mode="json"))


@router.post(
    "/chat",
    dependencies=[origin_guard_for_session, limit_by_conversation("chat", limit=30, window_seconds=600)],
)
async def chat(
    request: ChatRequest, session: Annotated[SessionClaims, Depends(require_session)]
) -> StreamingResponse:
    return await _run_turn(session, request)


@router.post(
    "/chat/resume",
    dependencies=[origin_guard_for_session, limit_by_conversation("chat", limit=30, window_seconds=600)],
)
async def resume(
    session: Annotated[SessionClaims, Depends(require_session)],
) -> StreamingResponse:
    """Answers the message the visitor was asked to identify for, now that they have. Same
    turn as before: the stored message and its id, so nothing is duplicated."""

    def find() -> ChatRequest | None:
        with SessionLocal() as db:
            pending = pending_message(db, conversation_id=session.conversation_id)
            if pending is None or pending.client_message_id is None:
                return None
            return ChatRequest(message=pending.content, message_id=pending.client_message_id)

    request = await run_in_threadpool(find)
    if request is None:
        raise HTTPException(status_code=404, detail={"code": "nothing_to_resume"})
    return await _run_turn(session, request)


async def _run_turn(session: SessionClaims, request: ChatRequest) -> StreamingResponse:
    # The tenant's scope overrides are read first: if the configuration cannot be read the turn
    # fails (a 503) before anything is opened, instead of leaving the conversation locked, and
    # without ignoring overrides that may restrict what this visitor can do.
    scope_overrides = await run_in_threadpool(_scope_overrides, session)
    # The turn is opened before streaming starts so a refusal can still be a proper
    # HTTP status instead of an event inside a 200 response.
    try:
        turn = await run_in_threadpool(_open_turn, session, request)
    except ActionNotOffered as missed:
        # Not an error: a button from an older question is a normal thing for a visitor to press.
        # Nothing is stored or run; the question that is open is shown again.
        stream = _replay(_NOT_UNDERSTOOD, session.conversation_id, missed.cards)
        return StreamingResponse(stream, media_type="text/event-stream")
    except TurnInProgress:
        raise HTTPException(status_code=409, detail={"code": "turn_in_progress"}) from None
    except MessageIdReused:
        raise HTTPException(status_code=409, detail={"code": "message_id_reused"}) from None
    except LookupError:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_session"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    background = None
    if turn.action is TurnAction.REPLAY:
        stream = _replay(turn.reply or "", session.conversation_id, turn.reply_cards)
    elif turn.action is TurnAction.HANDOFF:
        stream = _handed_off(session.conversation_id, turn.handoff)
    else:
        store = _DbTurnStore(session.conversation_id, turn)
        state = _TurnState()
        stream = stream_chat_turn(
            agent_graph, session, turn, store, state, scope_overrides=scope_overrides
        )
        # If the stream never starts (the client left right after the turn opened) the
        # generator's cleanup never runs; this frees the turn then, and does nothing else.
        background = BackgroundTask(_abandon_if_unsettled, state, store, session.conversation_id)
    return StreamingResponse(stream, media_type="text/event-stream", background=background)


@router.get("/conversations/{conversation_id}/messages", dependencies=[origin_guard_for_session])
async def conversation_messages(
    conversation_id: uuid.UUID, session: Annotated[SessionClaims, Depends(require_session)]
) -> MessageList:
    """The stored messages of the session's own conversation, so a reopened widget can
    show the history. Any other id is a 404, the same as one that does not exist."""
    if conversation_id != session.conversation_id:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found"})

    def read() -> tuple[list[Message], str]:
        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
            status = conversation.handoff_status if conversation else HandoffStatus.NONE
            return list_messages(db, conversation_id=conversation_id), status

    stored, handoff = await run_in_threadpool(read)
    return MessageList(
        messages=[StoredMessage.model_validate(m, from_attributes=True) for m in stored],
        handoff=handoff,
    )
