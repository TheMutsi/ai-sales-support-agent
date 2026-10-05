"""Typed contract for the deterministic output checks in `app/guardrails/`.

A guardrail check doesn't call an LLM, so it isn't wired through
`app/agent/prompts/` like the other nodes — it inspects what `response_writer`
already produced against the state that's supposed to ground it.
"""

from enum import StrEnum

from pydantic import BaseModel

from app.schemas.agent import Intent


class GuardrailSeverity(StrEnum):
    """BLOCK: the claim is falsifiable from state alone, so the response gets
    replaced outright — we're certain it's wrong, not just suspicious. FLAG: the
    signal is a heuristic that can false-positive on legitimate text, so it's
    only recorded for observability/evaluation, never used to rewrite a real
    answer."""

    BLOCK = "block"
    FLAG = "flag"


class OutputCheckContext(BaseModel):
    """What the output checks need to know about the turn, and nothing more.

    `guardrail_node` builds it from the graph state, so the checks depend on
    this contract instead of on the agent package (whose nodes call them)."""

    intent: Intent | None = None
    ticket_created: bool = False
    checkout_created: bool = False
    tool_call_rounds: int = 0
    # Instructions that must never appear verbatim in a reply.
    protected_prompt: str = ""


class GuardrailViolation(BaseModel):
    code: str
    severity: GuardrailSeverity
    message: str


class SafetyJudgment(BaseModel):
    """What `safety_judge_node` asks for — a focused second opinion, called
    only when `intent_router`'s own `safety_confidence` came back low. Unlike
    `IntentClassification`, this has no category to get right; it exists
    purely to decide whether the conversation should continue."""

    is_safe: bool
    reasoning: str
