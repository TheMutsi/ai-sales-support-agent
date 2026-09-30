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

from app.agent.state import AgentState
from app.guardrails.output_checks import run_output_guardrails
from app.schemas.guardrails import GuardrailSeverity

logger = logging.getLogger(__name__)

_FALLBACK_MESSAGE = (
    "No puedo confirmar ese resultado todavía — un agente humano lo va a revisar "
    "y te va a contactar con la información correcta."
)


def guardrail_node(state: AgentState) -> dict:
    response_message = state["messages"][-1]
    response_text = str(response_message.content)

    violations = run_output_guardrails(state, response_text)
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
        update["messages"] = [AIMessage(content=_FALLBACK_MESSAGE, id=response_message.id)]

    return update
