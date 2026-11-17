from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.schemas.model_facing import described_to_the_model


@described_to_the_model(
    "What `intent_router` classifies an incoming message as, driving which\n"
    "branch of the graph runs next."
)
class Intent(StrEnum):
    PRODUCT_QUESTION = "product_question"
    PRICING_QUESTION = "pricing_question"
    BILLING_QUESTION = "billing_question"
    TECHNICAL_SUPPORT = "technical_support"
    UPGRADE_REQUEST = "upgrade_request"
    REFUND_REQUEST = "refund_request"
    HUMAN_ESCALATION = "human_escalation"
    ORDER_STATUS = "order_status"
    ORDER_RETURN = "order_return"
    SMALL_TALK = "small_talk"
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
            "MewFlow request rather than an attempt to misuse the agent. Scored "
            "in the same call as intent, so a low value routes to a dedicated, "
            "more careful check (`safety_judge`) instead of paying for that "
            "second opinion on every message."
        ),
    )

    @field_validator("confidence", "safety_confidence", mode="before")
    @classmethod
    def _percentage_to_fraction(cls, value: object) -> object:
        if isinstance(value, int | float) and 1 < value <= 100:
            return value / 100
        return value


@described_to_the_model(
    "What a customer's message means for an order they want to reject or return."
)
class ReturnChoice(StrEnum):
    REJECT = "reject"
    REFUND = "refund"
    CREDITS = "credits"
    KEEP = "keep"
    UNCLEAR = "unclear"


@described_to_the_model(
    "What `order_return` asks the LLM to read from the conversation: only which order the\n"
    "customer means and which of these they said. Everything that follows is decided by rules."
)
class ReturnReading(BaseModel):
    order_id: str | None = Field(
        default=None,
        description="The order id the customer means, copied from the list, or null if unsure.",
    )
    choice: ReturnChoice
