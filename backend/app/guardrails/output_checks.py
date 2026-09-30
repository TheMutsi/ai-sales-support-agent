"""Deterministic, tool-grounded checks run on `response_writer`'s output.

These aren't an LLM judging another LLM's answer — each check is a plain
function comparing the response text against what the graph's `state` actually
confirms, the same "let code decide a fact a tool can compute" principle
(CLAUDE.md #1) applied to guardrails instead of business rules.
"""

import re

from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.schemas.agent import Intent
from app.schemas.guardrails import GuardrailSeverity, GuardrailViolation

_REFUND_CONFIRMATION_PATTERN = re.compile(
    r"(reembolso|devoluci[oó]n (de (tu|su) dinero)?|refund).{0,40}"
    r"(proces(ar[aá]|ad[oa])|aprobad|confirmad|emitid|"
    r"has been (approved|processed|issued)|will be (processed|issued|refunded))",
    re.IGNORECASE,
)

_CHECKOUT_LINK_PATTERN = re.compile(r"https?://\S*checkout\S*", re.IGNORECASE)

_BILLING_SPECULATION_PATTERN = re.compile(
    r"(podr[ií]a haber (habido|sido)|es posible que (se |te )?haya|"
    r"probablemente (se|te) (cobr|factur)|may have been charged|could have been)",
    re.IGNORECASE,
)

_TICKET_CREATION_CLAIM_PATTERN = re.compile(
    r"(he creado|ha creado|hemos creado|se cre[oó]|creamos|i('ve| have)? created|created a) "
    r".{0,20}ticket",
    re.IGNORECASE,
)

# Catches a specific ticket number/ID cited in either word order ("ticket
# number is #123" or "el número de ticket es 123") — when `ticket_receipt`
# is None there's no real number to cite, so this alone is unconditional.
_TICKET_NUMBER_CLAIM_PATTERN = re.compile(
    r"(ticket|caso)\D{0,25}\d{3,}|\d{3,}\D{0,25}(ticket|caso)",
    re.IGNORECASE,
)


def check_unconfirmed_refund_claim(
    state: AgentState, response_text: str
) -> GuardrailViolation | None:
    """No tool in `app/tools/` can issue a refund — every `refund_request` ends
    at `human_escalation`, which only creates a ticket. So any text reading as a
    refund being granted or already in motion is unconditionally false, not
    merely unverified, and gets blocked rather than just flagged."""
    if _REFUND_CONFIRMATION_PATTERN.search(response_text):
        return GuardrailViolation(
            code="unconfirmed_refund_claim",
            severity=GuardrailSeverity.BLOCK,
            message="Response implies a refund was approved/processed, but no tool confirmed one.",
        )
    return None


def check_checkout_without_eligibility(
    state: AgentState, response_text: str
) -> GuardrailViolation | None:
    """A checkout link is only legitimate once `business_rules_node` has run
    eligibility and `checkout_session` holds a real one — anything else is an
    invented link, which the CLAUDE.md guardrails section rules out explicitly."""
    if _CHECKOUT_LINK_PATTERN.search(response_text) and state.get("checkout_session") is None:
        return GuardrailViolation(
            code="checkout_without_eligibility",
            severity=GuardrailSeverity.BLOCK,
            message="Response includes a checkout link, but no checkout_session was created.",
        )
    return None


def check_system_prompt_leak(state: AgentState, response_text: str) -> GuardrailViolation | None:
    """Crude but reliable: the system prompt is a fixed string we own, so if a
    meaningful chunk of it shows up verbatim in the answer, the model leaked it
    rather than happening to agree with its content."""
    prompt_body = RESPONSE_WRITER_SYSTEM_PROMPT.split("\n\n")[0]
    if prompt_body and prompt_body in response_text:
        return GuardrailViolation(
            code="system_prompt_leak",
            severity=GuardrailSeverity.BLOCK,
            message="Response echoes the system prompt verbatim.",
        )
    return None


def check_fabricated_ticket_claim(
    state: AgentState, response_text: str
) -> GuardrailViolation | None:
    """Found live during Stage 6 verification, not hypothesized: a
    `billing_question` routes straight to `response_writer` (no ticket is ever
    created for it — see `route_after_customer_context`), and the model still
    told the customer a ticket had been created, with a fabricated ID lifted
    from their own UUID. `create_support_ticket` is the only thing that can
    make `ticket_receipt` non-`None`, so this is exactly as falsifiable as the
    refund check above."""
    if state.get("ticket_receipt") is None and (
        _TICKET_CREATION_CLAIM_PATTERN.search(response_text)
        or _TICKET_NUMBER_CLAIM_PATTERN.search(response_text)
    ):
        return GuardrailViolation(
            code="fabricated_ticket_claim",
            severity=GuardrailSeverity.BLOCK,
            message="Response claims a support ticket was created, but none exists in state.",
        )
    return None


def check_unverified_billing_explanation(
    state: AgentState, response_text: str
) -> GuardrailViolation | None:
    """Speculative language about *why* a charge happened ("podria haber...")
    is a softer signal than the other checks — legitimate hedging can look
    similar, so this only flags for Stage 9's evaluation dataset instead of
    rewriting a real answer on a heuristic that can false-positive."""
    if state.get("intent") == Intent.BILLING_QUESTION and _BILLING_SPECULATION_PATTERN.search(
        response_text
    ):
        return GuardrailViolation(
            code="unverified_billing_explanation",
            severity=GuardrailSeverity.FLAG,
            message="Response speculates about a charge without grounded billing data.",
        )
    return None


_ALL_CHECKS = (
    check_unconfirmed_refund_claim,
    check_checkout_without_eligibility,
    check_fabricated_ticket_claim,
    check_system_prompt_leak,
    check_unverified_billing_explanation,
)


def run_output_guardrails(state: AgentState, response_text: str) -> list[GuardrailViolation]:
    return [v for check in _ALL_CHECKS if (v := check(state, response_text)) is not None]
