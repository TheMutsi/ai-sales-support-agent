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
from app.schemas.agent import Intent
from app.schemas.guardrails import GuardrailSeverity, OutputCheckContext
from app.schemas.orders import OrderStatus, ReturnOutcome

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


def _confirmed_return_actions(state: AgentState) -> dict[str, bool]:
    """What the return step really did this turn, or what an order already says: the only things
    a reply may state as done."""
    result = state.get("return_result")
    outcome = result.outcome if result else None
    # What an order already says counts only when the customer is being told about their orders
    # (a status question), so an old refund cannot back a made-up new one in another answer.
    listed = (
        [o for o in [state.get("order_details"), *(state.get("customer_orders") or [])] if o]
        if state.get("intent") == Intent.ORDER_STATUS
        else []
    )
    return {
        "order_cancelled": outcome is ReturnOutcome.CANCELLED
        or any(o.status is OrderStatus.CANCELLED for o in listed),
        "refund_recorded": outcome is ReturnOutcome.KEPT_WITH_REFUND
        or any(o.retention and o.retention.refund_cents for o in listed),
        "points_credited": outcome is ReturnOutcome.KEPT_WITH_CREDITS
        or any(o.retention and o.retention.credit_points for o in listed),
        "offering": outcome in (ReturnOutcome.OFFER, ReturnOutcome.CONFIRM_CANCEL),
    }


def _output_check_context(state: AgentState) -> OutputCheckContext:
    return OutputCheckContext(
        intent=state.get("intent"),
        ticket_created=state.get("ticket_receipt") is not None,
        checkout_created=state.get("checkout_session") is not None,
        tool_call_rounds=state.get("tool_call_rounds", 0),
        order_found=state.get("order_details") is not None or bool(state.get("customer_orders")),
        **_confirmed_return_actions(state),
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
