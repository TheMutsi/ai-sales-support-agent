"""Wire contracts for `POST /api/chat`: the request body and the summary
carried by the final SSE `done` event.

The endpoint is stateless on the server: the graph isn't checkpointed, so
`messages` carries the full conversation so far, not just the latest turn —
the same shape as the Anthropic/OpenAI chat-completions APIs. The alternative
(a LangGraph checkpointer keyed by `conversation_id`) was considered and
dropped: `AgentState`'s per-turn fields (`customer_context`,
`checkout_session`, `ticket_receipt`, ...) are plain overwrites, not reducers,
so a checkpointed run would carry stale tool output from an earlier, unrelated
turn into one that never touched that node — e.g. a refund ticket from turn 1
still sitting in `response_writer`'s context on turn 3's pricing question.
Resending full history avoids that: every request is an independent graph run
starting from an empty state.

`customer_id` is required, not optional: every tool the graph can reach
(`get_customer_context`, `search_knowledge_base`, `create_support_ticket`)
takes a real UUID, and `Ticket.customer_id` is a non-nullable FK — there's no
"anonymous" path through the graph to design around.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.agent import Intent


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    customer_id: uuid.UUID
    messages: list[ChatMessage] = Field(min_length=1)
    conversation_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _last_message_is_from_the_user(self) -> "ChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be from the user — nothing to respond to.")
        return self


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
