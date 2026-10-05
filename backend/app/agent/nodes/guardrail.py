"""Runs after `response_writer`, before the graph ends.

The deterministic output checks (`app/guardrails/output_checks.py`) run
against the AI message `response_writer` just produced. A BLOCK violation
replaces that message with a safe fallback — the customer never sees the
unverified claim — and every violation (BLOCK or FLAG) lands on
`guardrail_flags` so Stage 9's evaluation suite can measure how often each
one actually fires, not just whether the final answer looked fine.
"""

import logging

from langchain_core.messages import AIMessage

from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.guardrails.output_checks import run_output_guardrails
from app.schemas.guardrails import GuardrailSeverity, OutputCheckContext

logger = logging.getLogger(__name__)

# Deliberately promises nothing: with no ticket, saying a human will follow
# up would be the same kind of unbacked claim the output checks exist to block.
_FALLBACK_MESSAGE = (
    "I can't confirm that information right now. If you'd like, ask to talk to "
    "a person and I'll connect you with our support team."
)

# When `human_escalation` did create a ticket, the blocked reply was the one
# place the customer would have learned that; the fallback must keep it.
_FALLBACK_WITH_TICKET_MESSAGE = (
    "I can't confirm that information right now, but I've created support ticket "
    "{ticket_id} and a person from our support team will follow up with you."
)


def _fallback_message(state: AgentState) -> str:
    if ticket_receipt := state.get("ticket_receipt"):
        return _FALLBACK_WITH_TICKET_MESSAGE.format(ticket_id=ticket_receipt.ticket_id)
    return _FALLBACK_MESSAGE


def _output_check_context(state: AgentState) -> OutputCheckContext:
    return OutputCheckContext(
        intent=state.get("intent"),
        ticket_created=state.get("ticket_receipt") is not None,
        checkout_created=state.get("checkout_session") is not None,
        tool_call_rounds=state.get("tool_call_rounds", 0),
        protected_prompt=RESPONSE_WRITER_SYSTEM_PROMPT,
    )


def guardrail_node(state: AgentState) -> dict:
    response_message = state["messages"][-1]
    response_text = str(response_message.content)

    violations = run_output_guardrails(_output_check_context(state), response_text)
    if not violations:
        return {}

    for violation in violations:
        logger.warning(
            "guardrail violation: %s",
            violation.message,
            extra={"guardrail_code": violation.code, "severity": violation.severity},
        )

    update: dict = {"guardrail_flags": [v.code for v in violations]}

    blocked = any(v.severity == GuardrailSeverity.BLOCK for v in violations)
    if blocked:
        # Replacing (not appending): reusing the same message id makes
        # `add_messages` overwrite the blocked content in place, so the
        # unverified claim never sits in conversation history either.
        update["messages"] = [AIMessage(content=_fallback_message(state), id=response_message.id)]

    return update
