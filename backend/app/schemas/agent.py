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
