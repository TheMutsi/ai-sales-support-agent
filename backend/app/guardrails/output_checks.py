import re

from app.schemas.agent import Intent
from app.schemas.guardrails import GuardrailSeverity, GuardrailViolation, OutputCheckContext

_REFUND_CONFIRMATION_PATTERN = re.compile(
    r"(reembolso|devoluci[oó]n (de (tu|su) dinero)?|refund).{0,40}"
    r"(proces(ar[aá]|ad[oa])|aprobad|confirmad|emitid|"
    r"has been (approved|processed|issued)|will be (processed|issued|refunded))",
    re.IGNORECASE,
)

_REFUND_DONE_PATTERN = re.compile(
    r"(reembolso|refund).{0,40}(has been|have been|was|ha sido|fue) "
    r"(approved|processed|issued|refunded|aprobad|procesad|emitid)|"
    r"\b(i|we)('ve| have) (refunded|processed|issued)",
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
    r".{0,20}(ticket|follow-up number|n[uú]mero de seguimiento)",
    re.IGNORECASE,
)

_TICKET_NUMBER_CLAIM_PATTERN = re.compile(
    r"(ticket|caso)\D{0,25}\d{3,}|\d{3,}\D{0,25}(ticket|caso)",
    re.IGNORECASE,
)

_FOLLOW_UP_NUMBER_PATTERN = re.compile(r"\bMF-[A-Z0-9]{8}\b", re.IGNORECASE)


_LOOKUP_CLAIM_PATTERN = re.compile(
    r"((checked|searched|looked (it )?up in|reviewed|consulted) (in )?(our|the|mewflow'?s?) "
    r"(documentation|docs|knowledge base)|"
    r"(based on|according to|per) (the information (in|from) )?(our|the|mewflow'?s?) "
    r"(documentation|docs|knowledge base)|"
    r"(revis[eé]|consult[eé]|busqu[eé]) (en )?(la|nuestra) (documentaci[oó]n|base de conocimiento)|"
    r"seg[uú]n (la|nuestra) (documentaci[oó]n|base de conocimiento))",
    re.IGNORECASE,
)

_BILLING_HISTORY_CLAIM_PATTERN = re.compile(
    r"(\bi('ve| have)? (checked|reviewed|looked (at|into|over)|gone through|went through|"
    r"verified|examined) (your |the )?(\w+ ){0,3}"
    r"(invoices?|billing history|payment history|charges|transactions|statements?)|"
    r"(revis[eé]|he revisado|verifiqu[eé]|he verificado) (tus|sus|la|las|el) "
    r"(\w+ ){0,2}(facturas?|cargos|historial de (pagos|facturaci[oó]n)))",
    re.IGNORECASE,
)

_INTERNAL_TOOL_TEXT_PATTERN = re.compile(r"\b([a-z]+_)+tool\b|\btool_calls?\b")


def check_unconfirmed_refund_claim(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    if context.refund_recorded:
        return None
    pattern = _REFUND_DONE_PATTERN if context.offering else _REFUND_CONFIRMATION_PATTERN
    if pattern.search(response_text):
        return GuardrailViolation(
            code="unconfirmed_refund_claim",
            severity=GuardrailSeverity.BLOCK,
            message="Response implies a refund was approved/processed, but no tool confirmed one.",
        )
    return None


_ORDER_CANCELLED_CLAIM_PATTERN = re.compile(
    r"\b(your|the|su|tu)\s+(order|pedido)\b[^.!?\n]{0,40}\b(has been|have been|was|is now|is|"
    r"ha sido|fue|qued[oó]|est[aá]) (cancel+ed|cancelad[oa])|"
    r"\b(i|we)('ve| have) cancel+ed\b|\b(he|hemos) cancelado\b",
    re.IGNORECASE,
)

_CREDITS_ADDED_CLAIM_PATTERN = re.compile(
    r"credits?.{0,40}\b(have been|has been|were|was|are now|ya fueron|ya se) (added|credited|acreditad)|"
    r"\b(i|we)('ve| have) (added|credited).{0,40}credits?|acreditamos.{0,40}cr[eé]ditos?",
    re.IGNORECASE,
)


def check_unbacked_order_action_claim(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    cancelled = not context.order_cancelled and _ORDER_CANCELLED_CLAIM_PATTERN.search(response_text)
    credited = not context.credits_added and _CREDITS_ADDED_CLAIM_PATTERN.search(response_text)
    if cancelled or credited:
        return GuardrailViolation(
            code="unbacked_order_action_claim",
            severity=GuardrailSeverity.BLOCK,
            message="Response says an order was cancelled or credits were added, but nothing did that.",
        )
    return None


def check_checkout_without_eligibility(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
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
    known = (context.escalation_reference or "").upper()
    invented_number = any(
        match.upper() != known for match in _FOLLOW_UP_NUMBER_PATTERN.findall(response_text)
    )
    if invented_number or (
        not context.ticket_created
        and (
            _TICKET_CREATION_CLAIM_PATTERN.search(response_text)
            or _TICKET_NUMBER_CLAIM_PATTERN.search(response_text)
        )
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
    if context.intent == Intent.BILLING_QUESTION and _BILLING_SPECULATION_PATTERN.search(
        response_text
    ):
        return GuardrailViolation(
            code="unverified_billing_explanation",
            severity=GuardrailSeverity.FLAG,
            message="Response speculates about a charge without grounded billing data.",
        )
    return None


_ORDER_NUMBER_REQUEST_PATTERN = re.compile(
    r"\b(provide|share|send|give|tell|confirm|enter|type|paste|proporcion\w*|compart\w*|"
    r"env[ií]\w*|ind[ií]c\w*|dime|dame)\b[^.?!]{0,40}"
    r"\b(order (number|id|no\b)|n[uú]mero de (pedido|orden)|id del pedido)",
    re.IGNORECASE,
)
_ORDER_CHECK_CLAIM_PATTERN = re.compile(
    r"\b(i('ve| have)?|we('ve| have)?)\s+(checked|looked (at|into|up)|reviewed|verified)\s+"
    r"(your|the)\s+(order|purchase)s?\b|"
    r"\bi\s+(can|will|'ll)\s+(check|look up|look into|verify)\s+(the status of\s+)?"
    r"(your|the)\s+(order|purchase)s?\b|"
    r"\b(revis[eé]|verifiqu[eé]|consult[eé])\s+(tu|el)\s+(pedido|compra)\b",
    re.IGNORECASE,
)
_NO_ORDER_ON_ACCOUNT_PATTERN = re.compile(
    r"\b(don'?t|do not|no)\s+(have|see|find)?\s*(an?\s+)?orders?\s+(associated|on file|"
    r"recorded|found|on your account)|no tengo (ning[uú]n )?pedido",
    re.IGNORECASE,
)

_INVOICE_MENTION_PATTERN = re.compile(r"\b(invoices?|facturas?)\b", re.IGNORECASE)

_NO_ACCESS_ADMISSION_PATTERN = re.compile(
    r"((i |we )?(don'?t|do not|can'?t|cannot|am unable to|am not able to)\s+"
    r"(have\s+)?(\w+\s+)?(access|information|details|ability|capability|means|see|view|retrieve|look up)|"
    r"no (tengo|puedo|dispongo)\b.{0,25}(acceso|informaci[oó]n|detalles|ver))",
    re.IGNORECASE,
)


def check_ungrounded_invoice_claim(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    if (
        context.intent == Intent.BILLING_QUESTION
        and context.tool_call_rounds == 0
        and _INVOICE_MENTION_PATTERN.search(response_text)
        and not _NO_ACCESS_ADMISSION_PATTERN.search(response_text)
    ):
        return GuardrailViolation(
            code="ungrounded_invoice_claim",
            severity=GuardrailSeverity.FLAG,
            message="Response states facts about invoices that no tool or search supports.",
        )
    return None


def check_unbacked_order_lookup(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    if context.intent == Intent.ORDER_STATUS or context.order_found:
        return None
    if (
        _ORDER_NUMBER_REQUEST_PATTERN.search(response_text)
        or _ORDER_CHECK_CLAIM_PATTERN.search(response_text)
        or _NO_ORDER_ON_ACCOUNT_PATTERN.search(response_text)
    ):
        return GuardrailViolation(
            code="unbacked_order_lookup",
            severity=GuardrailSeverity.BLOCK,
            message="Response asks for, or claims to have checked, an order nothing can look up.",
        )
    return None


_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@([\w-]+\.)+[a-z]{2,}", re.IGNORECASE)
_PUBLIC_EMAIL_DOMAIN = "@mewflow.example"
_PHONE_PATTERN = re.compile(
    r"\+\d[\d\s().-]{7,}\d|\(\d{2,4}\)\s?\d[\d\s.-]{5,}\d|\b\d{3}[\s.-]\d{3,4}[\s.-]\d{4}\b"
)
_GOVERNMENT_ID_PATTERN = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b|\b(?:ssn|ssi|dni|nif|nie|passport|pasaporte)\b\W{0,5}[A-Z0-9-]{6,}",
    re.IGNORECASE,
)


def check_sensitive_data_exposure(
    context: OutputCheckContext, response_text: str
) -> GuardrailViolation | None:
    allowed = {u.lower() for u in context.allowed_uuids}
    leaked_uuid = any(m.lower() not in allowed for m in _UUID_PATTERN.findall(response_text))
    leaked_email = any(
        not m.group(0).lower().endswith(_PUBLIC_EMAIL_DOMAIN)
        for m in _EMAIL_PATTERN.finditer(response_text)
    )
    if (
        leaked_uuid
        or leaked_email
        or _PHONE_PATTERN.search(response_text)
        or _GOVERNMENT_ID_PATTERN.search(response_text)
    ):
        return GuardrailViolation(
            code="sensitive_data_exposure",
            severity=GuardrailSeverity.BLOCK,
            message="Response contains an internal id or personal data.",
        )
    return None


_ALL_CHECKS = (
    check_sensitive_data_exposure,
    check_unconfirmed_refund_claim,
    check_checkout_without_eligibility,
    check_fabricated_ticket_claim,
    check_unverified_lookup_claim,
    check_fabricated_billing_history_claim,
    check_internal_tool_text,
    check_system_prompt_leak,
    check_unverified_billing_explanation,
    check_ungrounded_invoice_claim,
    check_unbacked_order_lookup,
    check_unbacked_order_action_claim,
)


def run_output_guardrails(
    context: OutputCheckContext, response_text: str
) -> list[GuardrailViolation]:
    return [v for check in _ALL_CHECKS if (v := check(context, response_text)) is not None]
