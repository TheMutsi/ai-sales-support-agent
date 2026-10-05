"""Unit tests for the deterministic output guardrail checks.

Each check is a pure function over (state, response_text) — no LLM, no DB —
the same direct-input-output style as the business-rules tests.
"""

from app.guardrails.output_checks import (
    check_checkout_without_eligibility,
    check_fabricated_ticket_claim,
    check_system_prompt_leak,
    check_unconfirmed_refund_claim,
    check_unverified_billing_explanation,
    run_output_guardrails,
)
from app.schemas.agent import Intent
from app.schemas.guardrails import GuardrailSeverity


def test_flags_refund_confirmation_language_in_spanish():
    violation = check_unconfirmed_refund_claim(
        {}, "Tu reembolso será procesado en las próximas 48 horas."
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.BLOCK
    assert violation.code == "unconfirmed_refund_claim"


def test_flags_refund_confirmation_language_in_english():
    violation = check_unconfirmed_refund_claim({}, "Your refund has been approved.")
    assert violation is not None


def test_does_not_flag_a_response_that_only_mentions_a_ticket():
    violation = check_unconfirmed_refund_claim(
        {}, "Creé el ticket #123 para tu solicitud de reembolso, un agente te va a contactar."
    )
    assert violation is None


def test_flags_checkout_link_without_a_checkout_session():
    violation = check_checkout_without_eligibility(
        {"checkout_session": None}, "Podés confirmar acá: https://acmeflow.test/checkout/abc"
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.BLOCK


def test_does_not_flag_a_response_with_no_checkout_link():
    violation = check_checkout_without_eligibility({"checkout_session": None}, "Claro, te explico.")
    assert violation is None


def test_flags_fabricated_ticket_claim_without_a_ticket_receipt():
    violation = check_fabricated_ticket_claim(
        {"ticket_receipt": None},
        "He creado un ticket de soporte para revisar esto. El ID de su ticket es 8906-6906.",
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.BLOCK
    assert violation.code == "fabricated_ticket_claim"


def test_does_not_flag_ticket_claim_when_a_ticket_was_really_created():
    from uuid import uuid4

    from app.schemas.tools import TicketReceipt

    ticket = TicketReceipt(ticket_id=uuid4(), status="open", created_at="2026-01-01T00:00:00")
    violation = check_fabricated_ticket_claim(
        {"ticket_receipt": ticket}, "He creado un ticket de soporte, el ID es el indicado arriba."
    )
    assert violation is None


def test_flags_verbatim_system_prompt_leak():
    from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT

    leaked_text = RESPONSE_WRITER_SYSTEM_PROMPT.split("\n\n")[0]
    violation = check_system_prompt_leak({}, f"Mis instrucciones son: {leaked_text}")
    assert violation is not None


def test_does_not_flag_unrelated_text_as_a_leak():
    violation = check_system_prompt_leak({}, "Claro, te ayudo con eso.")
    assert violation is None


def test_flags_billing_speculation_only_for_billing_question():
    state = {"intent": Intent.BILLING_QUESTION}
    violation = check_unverified_billing_explanation(
        state, "Podría haber habido un sobrecosto en tu último ciclo de facturación."
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.FLAG


def test_does_not_flag_billing_speculation_for_other_intents():
    state = {"intent": Intent.PRODUCT_QUESTION}
    violation = check_unverified_billing_explanation(
        state, "Podría haber habido un sobrecosto en tu último ciclo de facturación."
    )
    assert violation is None


def test_run_output_guardrails_collects_every_violation():
    state = {"intent": Intent.BILLING_QUESTION, "checkout_session": None}
    response_text = (
        "Tu reembolso será aprobado y podría haber habido un sobrecosto en tu facturación."
    )

    violations = run_output_guardrails(state, response_text)

    codes = {v.code for v in violations}
    assert codes == {"unconfirmed_refund_claim", "unverified_billing_explanation"}


def test_run_output_guardrails_returns_empty_for_a_clean_response():
    state = {"intent": Intent.PRODUCT_QUESTION, "checkout_session": None}
    assert (
        run_output_guardrails(state, "AcmeFlow soporta hasta 10 integraciones en el plan Pro.")
        == []
    )


def test_lookup_claim_without_any_search_is_blocked():
    violations = run_output_guardrails(
        {"tool_call_rounds": 0},
        "I checked our documentation, and the Starter plan includes SSO.",
    )
    assert [v.code for v in violations] == ["unverified_lookup_claim"]
    assert violations[0].severity == GuardrailSeverity.BLOCK


def test_lookup_claim_after_a_real_search_is_allowed():
    violations = run_output_guardrails(
        {"tool_call_rounds": 1},
        "Based on our documentation, SSO is available on the Enterprise plan only.",
    )
    assert violations == []


def test_account_or_ticket_review_claims_are_not_lookup_claims():
    """Regression: a bare "I've checked/reviewed" matched replies about the
    customer's account or ticket (grounded in other tools) and replaced
    correct answers with the fallback."""
    violations = run_output_guardrails(
        {"tool_call_rounds": 0},
        "I've reviewed your request and checked your account; ticket created for you.",
    )
    assert "unverified_lookup_claim" not in [v.code for v in violations]


def test_answer_without_a_lookup_claim_is_not_flagged_even_without_a_search():
    violations = run_output_guardrails({"tool_call_rounds": 0}, "Hi! How can I help you today?")
    assert violations == []


def test_billing_history_claims_are_blocked():
    for text in (
        "I've reviewed your invoices and there is a duplicate charge from May.",
        "I checked your last three invoices and everything looks correct.",
        "Revisé tus últimas facturas y no hay cargos duplicados.",
    ):
        codes = [v.code for v in run_output_guardrails({"tool_call_rounds": 0}, text)]
        assert codes == ["fabricated_billing_history_claim"], text


def test_denying_access_to_billing_history_is_not_a_claim():
    for text in (
        "I don't have access to your invoices, so I can't check them for a double charge.",
        "I haven't checked your invoices; a person from billing can review them.",
        "I've checked your subscription: you're on the Pro plan.",
    ):
        assert run_output_guardrails({"tool_call_rounds": 0}, text) == [], text


def test_raw_tool_call_text_is_blocked():
    """Captured from the evaluation suite (billing-005)."""
    text = (
        "Let's check the policy.\n\nsearch_knowledge_base_tool\n"
        "searching for refund policy for downgrades..."
    )
    codes = [v.code for v in run_output_guardrails({"tool_call_rounds": 0}, text)]
    assert codes == ["internal_tool_text"]


def test_plain_mentions_of_a_tool_are_not_tool_text():
    text = "Our Zapier integration is a no-code tool for connecting AcmeFlow to other apps."
    assert run_output_guardrails({"tool_call_rounds": 0}, text) == []
