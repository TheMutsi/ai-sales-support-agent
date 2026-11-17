from enum import StrEnum

from pydantic import BaseModel

from app.schemas.agent import Intent
from app.schemas.model_facing import described_to_the_model


class GuardrailSeverity(StrEnum):
    BLOCK = "block"
    FLAG = "flag"


class OutputCheckContext(BaseModel):
    intent: Intent | None = None
    ticket_created: bool = False
    escalation_reference: str | None = None
    checkout_created: bool = False
    tool_call_rounds: int = 0
    order_found: bool = False
    order_cancelled: bool = False
    refund_recorded: bool = False
    credits_added: bool = False
    offering: bool = False
    allowed_uuids: list[str] = []
    protected_prompt: str = ""


class GuardrailViolation(BaseModel):
    code: str
    severity: GuardrailSeverity
    message: str


@described_to_the_model(
    "What `safety_judge_node` asks for — a focused second opinion, called\n"
    "only when `intent_router`'s own `safety_confidence` came back low. Unlike\n"
    "`IntentClassification`, this has no category to get right; it exists\n"
    "purely to decide whether the conversation should continue."
)
class SafetyJudgment(BaseModel):
    is_safe: bool
    reasoning: str
