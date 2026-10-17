"""Wire contracts for `POST /api/chat`: the request body and the summary
carried by the final SSE `done` event.

The request carries only the new message. The history lives on the server
(`app.chat.turns`): a client that resends it can forge assistant messages, which is
prompt injection through the history. The graph isn't checkpointed: `AgentState`'s
per-turn fields are plain overwrites, not reducers, so a checkpointed run would carry
stale tool output into a turn that never touched that node. Each turn is an independent
graph run started from the stored plain user/assistant text.

`message_id` is an idempotency key chosen by the client: sending it again replays the
stored reply instead of running the agent twice. Who is talking and in which
conversation comes from the session (`Authorization: Bearer ...`), never from the body.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.agent import Intent
from app.schemas.rag import SourceReference
from app.schemas.tools import CheckoutSession


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    message_id: uuid.UUID


class ChatTurnSummary(BaseModel):
    """Payload of the SSE `done` event that closes every chat turn.

    Exposes the structural outcome of the graph run (routing decision,
    guardrail activity, escalation, eligibility) so clients don't have to
    infer it from the response text. Every field is read from state the
    graph's own nodes set deterministically. Defined once here so the
    endpoint that emits it and any client that parses it (e.g. the
    evaluation runner) share a single, validated contract.
    """

    conversation_id: uuid.UUID
    intent: Intent | None = None
    guardrail_flags: list[str] = Field(default_factory=list)
    ticket_created: bool = False
    escalated: bool = False
    # Only computed for `upgrade_request` (business_rules_node); `None` means
    # "not evaluated", which is different from "evaluated and not eligible".
    upgrade_eligible: bool | None = None
    tool_call_rounds: int = 0
    # True when either input-safety tier (regex pre-filter or safety_judge)
    # refused the turn before it reached any other node.
    input_blocked: bool = False
    # intent_router's own score; `None` when the regex tier blocked the turn
    # before intent_router ran, and always in production (see
    # `_summarize_turn`). Exposed so the routing threshold can be calibrated
    # against labeled cases instead of guessed.
    safety_confidence: float | None = None

    # What the answer drew on and what the turn produced, so the client can
    # render citations and result cards from structured data instead of
    # parsing the response text. All read from tool results in state, never
    # from the model's words.
    sources: list[SourceReference] = Field(default_factory=list)
    checkout: CheckoutSession | None = None
    ticket_id: uuid.UUID | None = None
