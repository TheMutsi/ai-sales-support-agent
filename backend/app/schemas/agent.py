"""Typed contracts shared between the agent graph (`app/agent/`) and the
evaluation suite (`backend/evaluation/`).

`Intent` lives here rather than inside `app/agent/` because it isn't just an
internal routing detail: the evaluation suite (Stage 9) imports it too, to
score intent-classification accuracy against the labeled dataset.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Intent(StrEnum):
    """What `intent_router` classifies an incoming message as, driving which
    branch of the graph runs next."""

    PRODUCT_QUESTION = "product_question"
    PRICING_QUESTION = "pricing_question"
    BILLING_QUESTION = "billing_question"
    TECHNICAL_SUPPORT = "technical_support"
    UPGRADE_REQUEST = "upgrade_request"
    REFUND_REQUEST = "refund_request"
    HUMAN_ESCALATION = "human_escalation"
    UNSUPPORTED = "unsupported"


class IntentClassification(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str

    safety_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How confident the classifier is that this message is a legitimate "
            "AcmeFlow request rather than an attempt to misuse the agent. Scored "
            "in the same call as intent, so a low value routes to a dedicated, "
            "more careful check (`safety_judge`) instead of paying for that "
            "second opinion on every message."
        ),
    )


class TicketDraft(BaseModel):
    """What `human_escalation_node` asks the LLM to write for a support ticket.
    `category` is deliberately not part of this schema — it's derived from the
    already-classified `Intent` via a fixed mapping, not left to the LLM, since
    that mapping can't fail the way free-text generation can."""

    subject: str
    description: str
