import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.business.escalation import EscalationRoute
from app.schemas.agent import Intent
from app.schemas.cards import Card, CardAction
from app.schemas.rag import SourceReference
from app.schemas.tools import CheckoutSession


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class StoredMessage(BaseModel):
    seq: int
    role: Literal["user", "assistant", "human", "system"]
    kind: Literal["text", "identity_request", "system"]
    content: str
    author_name: str | None = Field(
        default=None, description="The name a person's message is shown under."
    )
    cards: list[Card] = Field(default_factory=list)
    created_at: datetime

    @field_validator("cards", mode="before")
    @classmethod
    def _no_cards_is_an_empty_list(cls, value: object) -> object:
        if value is None:
            return []
        still_known_types = {"action", "product", "divider"}
        return [c for c in value if not isinstance(c, dict) or c.get("type") in still_known_types]


class MessageList(BaseModel):
    messages: list[StoredMessage]
    handoff: Literal["none", "waiting", "active"] = Field(
        default="none", description="`waiting` or `active` while a person has the conversation."
    )


class TextInput(BaseModel):
    type: Literal["text"] = "text"
    message: str = Field(min_length=1)


class ActionInput(BaseModel):
    type: Literal["action"]
    action: CardAction
    order_id: str | None = Field(default=None, max_length=64)


ChatInput = Annotated[TextInput | ActionInput, Field(discriminator="type")]


class ChatRequest(BaseModel):
    message_id: uuid.UUID
    input: ChatInput

    @model_validator(mode="before")
    @classmethod
    def _plain_message(cls, data):
        if isinstance(data, dict) and "input" not in data and "message" in data:
            rest = {k: v for k, v in data.items() if k != "message"}
            data = {**rest, "input": {"type": "text", "message": data["message"]}}
        return data


class ChatTurnSummary(BaseModel):
    conversation_id: uuid.UUID
    handoff: Literal["waiting", "active"] | None = Field(
        default=None,
        description="Set when a person has the conversation: the message was stored, no one else answers it.",
    )
    intent: Intent | None = None
    guardrail_flags: list[str] = Field(default_factory=list)
    ticket_created: bool = False
    escalated: bool = False
    upgrade_eligible: bool | None = Field(
        default=None,
        description="Only computed for `upgrade_request`; `null` means not evaluated, not ineligible.",
    )
    tool_call_rounds: int = 0
    input_blocked: bool = Field(
        default=False, description="An input-safety tier refused the turn before any other step."
    )
    safety_confidence: float | None = Field(
        default=None,
        description=(
            "The classifier's own safety score, for calibrating the routing threshold. Null when "
            "the regex tier blocked the turn, and always in production."
        ),
    )

    sources: list[SourceReference] = Field(default_factory=list)
    checkout: CheckoutSession | None = None
    escalation_reference: str | None = Field(
        default=None, description="The follow-up number of an escalation opened this turn."
    )
    escalation_route: EscalationRoute | None = Field(
        default=None, description="The widget waits for a person only when this is `live`."
    )

    identity_required: bool = False
    identity_methods: list[str] = Field(
        default_factory=list,
        description="Forms the widget offers (`otp`, `order_id`); empty means only the shop's login.",
    )
    cards: list[Card] = Field(default_factory=list)


class ContextUpdate(BaseModel):
    properties: dict[str, str | None] = Field(default_factory=dict, max_length=20)
    add_tags: list[str] = Field(default_factory=list, max_length=20)
    remove_tags: list[str] = Field(default_factory=list, max_length=20)


class ConversationContext(BaseModel):
    properties: dict[str, str]
    tags: list[str]
