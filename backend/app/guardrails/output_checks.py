"""Deterministic, tool-grounded checks run on `response_writer`'s output.

These aren't an LLM judging another LLM's answer — each check is a plain
function comparing the response text against what the turn's context actually
confirms, the same "let code decide a fact a tool can compute" principle
(CLAUDE.md #1) applied to guardrails instead of business rules.
"""

import re

from app.schemas.agent import Intent
from app.schemas.guardrails import GuardrailSeverity, GuardrailViolation, OutputCheckContext

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
# number is #123" or "123 is your ticket number") — when `ticket_receipt`
# is None there's no real number to cite, so this alone is unconditional.
_TICKET_NUMBER_CLAIM_PATTERN = re.compile(
    r"(ticket|caso)\D{0,25}\d{3,}|\d{3,}\D{0,25}(ticket|caso)",
    re.IGNORECASE,
)


# Claims of having consulted the knowledge base. Spanish alternatives are kept
# alongside English, like the patterns above, because the agent replies in
# the customer's language.
# Requires an explicit documentation/knowledge-base object: a bare "I've
# checked" also covers legitimate statements about the customer's account or
# a ticket, which come from other tools and must not be blocked.
_LOOKUP_CLAIM_PATTERN = re.compile(
    r"((checked|searched|looked (it )?up in|reviewed|consulted) (in )?(our|the|acmeflow'?s?) "
    r"(documentation|docs|knowledge base)|"
    r"(based on|according to|per) (the information (in|from) )?(our|the|acmeflow'?s?) "
    r"(documentation|docs|knowledge base)|"
    r"(revis[eé]|consult[eé]|busqu[eé]) (en )?(la|nuestra) (documentaci[oó]n|base de conocimiento)|"
    r"seg[uú]n (la|nuestra) (documentaci[oó]n|base de conocimiento))",
    re.IGNORECASE,
)

# First-person claims of having looked at the customer's billing records. No
# tool exposes invoices, charges or payment history (`CustomerContext` only
# carries the current subscription), so any such claim is fabricated.
_BILLING_HISTORY_CLAIM_PATTERN = re.compile(
    r"(\bi('ve| have)? (checked|reviewed|looked (at|into|over)|gone through|went through|"
    r"verified|examined) (your |the )?(\w+ ){0,3}"
    r"(invoices?|billing history|payment history|charges|transactions|statements?)|"
    r"(revis[eé]|he revisado|verifiqu[eé]|he verificado) (tus|sus|la|las|el) "
    r"(\w+ ){0,2}(facturas?|cargos|historial de (pagos|facturaci[oó]n)))",
    re.IGNORECASE,
)

# Raw tool-call syntax written into the reply text instead of a real tool
# call: snake_case tool identifiers (`search_knowledge_base_tool`) or
# `tool_call(s)`. A customer never has a reason to see either.
_INTERNAL_TOOL_TEXT_PATTERN = re.compile(r"\b([a-z]+_)+tool\b|\btool_calls?\b")


def check_unconfirmed_refund_claim(
    context: OutputCheckContext, response_text: str
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
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    """A checkout link is only legitimate once `business_rules_node` has run
    eligibility and `checkout_session` holds a real one — anything else is an
    invented link, which the CLAUDE.md guardrails section rules out explicitly."""
    if _CHECKOUT_LINK_PATTERN.search(response_text) and not context.checkout_created:
        return GuardrailViolation(
            code="checkout_without_eligibility",
            severity=GuardrailSeverity.BLOCK,
            message="Response includes a checkout link, but no checkout_session was created.",
        )
    return None


def check_system_prompt_leak(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    """Crude but reliable: the system prompt is a fixed string we own, so if a
    meaningful chunk of it shows up verbatim in the answer, the model leaked it
    rather than happening to agree with its content."""
    prompt_body = context.protected_prompt.split("\n\n")[0]
    if prompt_body and prompt_body in response_text:
        return GuardrailViolation(
            code="system_prompt_leak",
            severity=GuardrailSeverity.BLOCK,
            message="Response echoes the system prompt verbatim.",
        )
    return None


def check_fabricated_ticket_claim(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    """Found live during Stage 6 verification, not hypothesized: a
    `billing_question` routes straight to `response_writer` (no ticket is ever
    created for it — see `route_after_customer_context`), and the model still
    told the customer a ticket had been created, with a fabricated ID lifted
    from their own UUID. `create_support_ticket` is the only thing that can
    make `ticket_receipt` non-`None`, so this is exactly as falsifiable as the
    refund check above."""
    if not context.ticket_created and (
        _TICKET_CREATION_CLAIM_PATTERN.search(response_text)
        or _TICKET_NUMBER_CLAIM_PATTERN.search(response_text)
    ):
        return GuardrailViolation(
            code="fabricated_ticket_claim",
            severity=GuardrailSeverity.BLOCK,
            message="Response claims a support ticket was created, but no ticket exists.",
        )
    return None


def check_unverified_lookup_claim(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    """Found by the evaluation suite: the model answered "I checked our
    documentation, and the Starter plan includes SSO" (false: SSO is
    Enterprise-only) without having called the knowledge base tool at all.
    `tool_call_rounds` is the graph's own record of whether a search ran, so a
    claim of having consulted the documentation with zero rounds is false by
    construction, and the content it vouches for is ungrounded."""
    if context.tool_call_rounds == 0 and _LOOKUP_CLAIM_PATTERN.search(response_text):
        return GuardrailViolation(
            code="unverified_lookup_claim",
            severity=GuardrailSeverity.BLOCK,
            message="Response claims to have consulted the documentation, but no search ran.",
        )
    return None


def check_fabricated_billing_history_claim(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    """Found by the evaluation suite: asked to check a double charge, the
    model said it had reviewed the customer's invoices. No tool can read
    invoices, so the claim and anything it concludes from them are invented."""
    if _BILLING_HISTORY_CLAIM_PATTERN.search(response_text):
        return GuardrailViolation(
            code="fabricated_billing_history_claim",
            severity=GuardrailSeverity.BLOCK,
            message="Response claims to have reviewed billing records no tool can access.",
        )
    return None


def check_internal_tool_text(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    """Found by the evaluation suite: on a path with no tool bound, the model
    wrote `search_knowledge_base_tool` and a fake "searching..." step into its
    reply. That narrates a search that never ran, so it is blocked like the
    other unbacked claims rather than shown to the customer."""
    if _INTERNAL_TOOL_TEXT_PATTERN.search(response_text):
        return GuardrailViolation(
            code="internal_tool_text",
            severity=GuardrailSeverity.BLOCK,
            message="Response contains raw tool-call text instead of an answer.",
        )
    return None


def check_unverified_billing_explanation(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    """Speculative language about *why* a charge happened ("podria haber...")
    is a softer signal than the other checks — legitimate hedging can look
    similar, so this only flags for Stage 9's evaluation dataset instead of
    rewriting a real answer on a heuristic that can false-positive."""
    if context.intent == Intent.BILLING_QUESTION and _BILLING_SPECULATION_PATTERN.search(
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
    check_unverified_lookup_claim,
    check_fabricated_billing_history_claim,
    check_internal_tool_text,
    check_system_prompt_leak,
    check_unverified_billing_explanation,
)


def run_output_guardrails(
    context: OutputCheckContext, response_text: str
) -> list[GuardrailViolation]:
    return [v for check in _ALL_CHECKS if (v := check(context, response_text)) is not None]
