import logging

from langchain_core.messages import AIMessage

from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.guardrails.output_checks import run_output_guardrails
from app.schemas.agent import Intent
from app.schemas.guardrails import GuardrailSeverity, OutputCheckContext
from app.schemas.orders import OrderStatus, ReturnOutcome

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "I can't confirm that information right now. If you'd like, ask to talk to "
    "a person and I'll connect you with our support team."
)

_FALLBACK_WITH_ESCALATION_MESSAGE = (
    "I can't confirm that information right now, but I've passed this to our support team "
    "(follow-up number {reference}) and a person will follow up with you."
)


def _fallback_message(state: AgentState) -> str:
    if receipt := state.get("escalation_receipt"):
        return _FALLBACK_WITH_ESCALATION_MESSAGE.format(reference=receipt.reference)
    return FALLBACK_MESSAGE


def _with_follow_up_number(state: AgentState, text: str) -> str | None:
    receipt = state.get("escalation_receipt")
    if receipt is None or receipt.reference in text:
        return None
    return f"{text}\n\nYour follow-up number is {receipt.reference}."


def _confirmed_return_actions(state: AgentState) -> dict[str, bool]:
    result = state.get("return_result")
    outcome = result.outcome if result else None
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
        "credits_added": outcome is ReturnOutcome.KEPT_WITH_CREDITS
        or any(o.retention and o.retention.credit_cents for o in listed),
        "offering": outcome in (ReturnOutcome.OFFER, ReturnOutcome.CONFIRM_CANCEL),
    }


def _escalation_reference(state: AgentState) -> str | None:
    escalation = state.get("escalation_receipt") or state.get("open_escalation")
    return escalation.reference if escalation else None


def _output_check_context(state: AgentState) -> OutputCheckContext:
    return OutputCheckContext(
        intent=state.get("intent"),
        ticket_created=state.get("escalation_receipt") is not None,
        escalation_reference=_escalation_reference(state),
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
        if (with_number := _with_follow_up_number(state, response_text)) is not None:
            return {"messages": [AIMessage(content=with_number, id=response_message.id)]}
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
        update["messages"] = [AIMessage(content=_fallback_message(state), id=response_message.id)]
    elif (with_number := _with_follow_up_number(state, response_text)) is not None:
        update["messages"] = [AIMessage(content=with_number, id=response_message.id)]

    return update
