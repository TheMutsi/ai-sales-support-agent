"""Unit tests for the deterministic output guardrail checks.

Each check is a pure function over (state, response_text) — no LLM, no DB —
the same direct-input-output style as the business-rules tests.
"""

from app.guardrails.output_checks import (
    check_checkout_without_eligibility,
    check_fabricated_ticket_claim,
    check_system_prompt_leak,
    check_unbacked_order_lookup,
    check_unconfirmed_refund_claim,
    check_ungrounded_invoice_claim,
    check_unverified_billing_explanation,
    run_output_guardrails,
)
from app.schemas.agent import Intent
from app.schemas.guardrails import GuardrailSeverity, OutputCheckContext


def test_flags_refund_confirmation_language_in_spanish():
    violation = check_unconfirmed_refund_claim(
        OutputCheckContext(), "Tu reembolso será procesado en las próximas 48 horas."
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.BLOCK
    assert violation.code == "unconfirmed_refund_claim"


def test_flags_refund_confirmation_language_in_english():
    violation = check_unconfirmed_refund_claim(
        OutputCheckContext(), "Your refund has been approved."
    )
    assert violation is not None


def test_does_not_flag_a_response_that_only_mentions_a_ticket():
    violation = check_unconfirmed_refund_claim(
        OutputCheckContext(),
        "Creé el ticket #123 para tu solicitud de reembolso, un agente te va a contactar.",
    )
    assert violation is None


def test_flags_checkout_link_without_a_checkout_session():
    violation = check_checkout_without_eligibility(
        OutputCheckContext(), "Podés confirmar acá: https://mewflow.test/checkout/abc"
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.BLOCK


def test_does_not_flag_a_response_with_no_checkout_link():
    violation = check_checkout_without_eligibility(OutputCheckContext(), "Claro, te explico.")
    assert violation is None


def test_flags_fabricated_ticket_claim_without_a_ticket_receipt():
    violation = check_fabricated_ticket_claim(
        OutputCheckContext(),
        "He creado un ticket de soporte para revisar esto. El ID de su ticket es 8906-6906.",
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.BLOCK
    assert violation.code == "fabricated_ticket_claim"


def test_does_not_flag_ticket_claim_when_a_ticket_was_really_created():
    violation = check_fabricated_ticket_claim(
        OutputCheckContext(ticket_created=True),
        "He creado un ticket de soporte, el ID es el indicado arriba.",
    )
    assert violation is None


_PROTECTED = OutputCheckContext(
    protected_prompt="You are a test assistant with secret rules.\n\nMore instructions."
)


def test_flags_verbatim_system_prompt_leak():
    violation = check_system_prompt_leak(
        _PROTECTED, "My instructions are: You are a test assistant with secret rules."
    )
    assert violation is not None


def test_does_not_flag_unrelated_text_as_a_leak():
    assert check_system_prompt_leak(_PROTECTED, "Sure, I can help with that.") is None


def test_flags_billing_speculation_only_for_billing_question():
    state = OutputCheckContext(intent=Intent.BILLING_QUESTION)
    violation = check_unverified_billing_explanation(
        state, "Podría haber habido un sobrecosto en tu último ciclo de facturación."
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.FLAG


def test_does_not_flag_billing_speculation_for_other_intents():
    state = OutputCheckContext(intent=Intent.PRODUCT_QUESTION)
    violation = check_unverified_billing_explanation(
        state, "Podría haber habido un sobrecosto en tu último ciclo de facturación."
    )
    assert violation is None


def test_run_output_guardrails_collects_every_violation():
    state = OutputCheckContext(intent=Intent.BILLING_QUESTION)
    response_text = (
        "Tu reembolso será aprobado y podría haber habido un sobrecosto en tu facturación."
    )

    violations = run_output_guardrails(state, response_text)

    codes = {v.code for v in violations}
    assert codes == {"unconfirmed_refund_claim", "unverified_billing_explanation"}


def test_run_output_guardrails_returns_empty_for_a_clean_response():
    state = OutputCheckContext(intent=Intent.PRODUCT_QUESTION)
    assert (
        run_output_guardrails(state, "MewFlow soporta hasta 10 integraciones en el plan Pro.")
        == []
    )


def test_lookup_claim_without_any_search_is_blocked():
    violations = run_output_guardrails(
        OutputCheckContext(tool_call_rounds=0),
        "I checked our documentation, and the Starter plan includes SSO.",
    )
    assert [v.code for v in violations] == ["unverified_lookup_claim"]
    assert violations[0].severity == GuardrailSeverity.BLOCK


def test_lookup_claim_after_a_real_search_is_allowed():
    violations = run_output_guardrails(
        OutputCheckContext(tool_call_rounds=1),
        "Based on our documentation, SSO is available on the Enterprise plan only.",
    )
    assert violations == []


def test_account_or_ticket_review_claims_are_not_lookup_claims():
    """Regression: a bare "I've checked/reviewed" matched replies about the
    customer's account or ticket (grounded in other tools) and replaced
    correct answers with the fallback."""
    violations = run_output_guardrails(
        OutputCheckContext(tool_call_rounds=0),
        "I've reviewed your request and checked your account; ticket created for you.",
    )
    assert "unverified_lookup_claim" not in [v.code for v in violations]


def test_answer_without_a_lookup_claim_is_not_flagged_even_without_a_search():
    violations = run_output_guardrails(
        OutputCheckContext(tool_call_rounds=0), "Hi! How can I help you today?"
    )
    assert violations == []


def test_billing_history_claims_are_blocked():
    for text in (
        "I've reviewed your invoices and there is a duplicate charge from May.",
        "I checked your last three invoices and everything looks correct.",
        "Revisé tus últimas facturas y no hay cargos duplicados.",
    ):
        codes = [
            v.code for v in run_output_guardrails(OutputCheckContext(tool_call_rounds=0), text)
        ]
        assert codes == ["fabricated_billing_history_claim"], text


def test_denying_access_to_billing_history_is_not_a_claim():
    for text in (
        "I don't have access to your invoices, so I can't check them for a double charge.",
        "I haven't checked your invoices; a person from billing can review them.",
        "I've checked your subscription: you're on the Pro plan.",
    ):
        assert run_output_guardrails(OutputCheckContext(tool_call_rounds=0), text) == [], text


def test_raw_tool_call_text_is_blocked():
    """Captured from the evaluation suite (billing-005)."""
    text = (
        "Let's check the policy.\n\nsearch_knowledge_base_tool\n"
        "searching for refund policy for downgrades..."
    )
    codes = [v.code for v in run_output_guardrails(OutputCheckContext(tool_call_rounds=0), text)]
    assert codes == ["internal_tool_text"]


def test_plain_mentions_of_a_tool_are_not_tool_text():
    text = "Our Zapier integration is a no-code tool for connecting MewFlow to other apps."
    assert run_output_guardrails(OutputCheckContext(tool_call_rounds=0), text) == []


# --- check_ungrounded_invoice_claim ------------------------------------------------------
# The responses below are real ones from the agent (qwen2.5:7b-instruct), captured while
# measuring billing-006 to billing-009. No tool can read invoices, so any fact the model states
# about them is invented unless it first searched the knowledge base.

_BILLING = OutputCheckContext(intent=Intent.BILLING_QUESTION, tool_call_rounds=0)


def test_flags_an_invented_invoice_fact_without_any_knowledge_base_search():
    violation = check_ungrounded_invoice_claim(
        _BILLING,
        "Your subscription is active until November 6, 2026. There are no upcoming invoices "
        "mentioned in your account details.",
    )
    assert violation is not None
    assert violation.severity == GuardrailSeverity.FLAG
    assert violation.code == "ungrounded_invoice_claim"


def test_flags_invented_invoice_features_even_when_worded_differently():
    assert check_ungrounded_invoice_claim(
        _BILLING,
        "Unfortunately, our system doesn't currently offer a preview feature or a dashboard to "
        "view invoices. However, you can expect to receive an invoice email before the charge.",
    )
    assert check_ungrounded_invoice_claim(_BILLING, "No tienes facturas próximas programadas.")


def test_does_not_flag_an_honest_admission_of_no_access():
    for honest in (
        (
            "I don't have access to view your next invoice details directly. Would you like me "
            "to search for this information in our knowledge base?"
        ),
        (
            "I don't have specific details about the invoice amount as that information isn't "
            "provided in your account context."
        ),
        "No tengo acceso a tus facturas, pero puedo buscar en la base de conocimiento.",
        # Real response from billing-006: an admission worded with "ability", not "access".
        (
            "I'm sorry, but I currently don't have the ability to send invoices directly. "
            "My knowledge is primarily focused on your subscription and account details."
        ),
    ):
        assert check_ungrounded_invoice_claim(_BILLING, honest) is None, honest


def test_does_not_flag_when_the_knowledge_base_was_searched_this_turn():
    context = OutputCheckContext(intent=Intent.BILLING_QUESTION, tool_call_rounds=1)
    assert (
        check_ungrounded_invoice_claim(
            context, "An invoice is emailed to the account owner after each monthly charge."
        )
        is None
    )


def test_does_not_flag_a_response_that_never_mentions_invoices():
    assert (
        check_ungrounded_invoice_claim(
            _BILLING, "Your Starter plan is active and renews on November 6, 2026."
        )
        is None
    )


def test_invoice_check_only_applies_to_billing_questions():
    context = OutputCheckContext(intent=Intent.PRODUCT_QUESTION, tool_call_rounds=0)
    assert check_ungrounded_invoice_claim(context, "You have no upcoming invoices.") is None


def test_known_gap_an_honest_opening_hides_an_invented_follow_up():
    """Documented limitation, not a goal: the admission of no access wins, so a response that
    admits it and then invents a feature in the same breath is not flagged. Catching it needs
    a semantic check; the evaluation (billing-008) is what measures how often it happens."""
    assert (
        check_ungrounded_invoice_claim(
            _BILLING,
            "I don't have information about a dashboard where you can view invoices, but you "
            "can preview your invoice before being charged in the billing section.",
        )
        is None
    )


def test_a_correct_answer_about_a_refunded_order_is_not_taken_for_an_unconfirmed_refund():
    """The order data says `refunded`, so saying so is grounded. Real answers from the
    evaluation (order-003) must pass the guard that blocks invented refund confirmations.
    Not a guarantee: "the refund has been processed" would still match its pattern."""
    for answer in (
        (
            "Yes, your order was refunded. It was placed on 2026-09-17 and the plan starter was "
            "refunded for $29.00 USD."
        ),
        (
            "Yes, your order was refunded. The order details are as follows: plan starter, "
            "$29.00 USD, status refunded, placed on 2026-09-17."
        ),
    ):
        assert check_unconfirmed_refund_claim(OutputCheckContext(), answer) is None, answer


# --- check_unbacked_order_lookup -------------------------------------------------------------
# Real replies from the evaluation (order-010 to order-012, a logged-in customer saying "refund
# for my order", "cancel my order", "my purchase was charged twice"). No tool reads orders on
# these paths and the session names no order, so asking for an order number, saying one was
# checked, or saying there is none on the account are all things the agent cannot back.

_NO_ORDER = OutputCheckContext(intent=Intent.REFUND_REQUEST, order_found=False)


def test_blocks_asking_for_an_order_number_that_cannot_be_looked_up():
    for reply in (
        (
            "I understand you'd like a refund for your order. Could you please provide me with "
            "the order number so I can check the details?"
        ),
        "Could you please provide the order number so I can assist you further?",
        "¿Podrías compartir el número de pedido para revisarlo?",
    ):
        violation = check_unbacked_order_lookup(_NO_ORDER, reply)
        assert violation is not None and violation.severity == GuardrailSeverity.BLOCK, reply
        assert violation.code == "unbacked_order_lookup"


def test_blocks_claiming_to_have_checked_or_to_be_able_to_check_an_order():
    for reply in (
        "I've checked your order, but it seems there is only one purchase recorded.",
        "I can check the status of your order to see if there were any charges applied twice.",
        "Revisé tu pedido y no encuentro cargos duplicados.",
    ):
        assert check_unbacked_order_lookup(_NO_ORDER, reply) is not None, reply


def test_blocks_saying_there_is_no_order_on_the_account_when_nothing_could_say_so():
    reply = "I'm sorry, but I don't have an order associated with your account."
    assert check_unbacked_order_lookup(_NO_ORDER, reply) is not None


def test_an_order_status_answer_may_say_it_could_not_find_the_order():
    """The order_status step did read the order: "no order with that number" is a fact there."""
    context = OutputCheckContext(intent=Intent.ORDER_STATUS, order_found=False)
    for reply in (
        "I could not find an order with that number. Could you check the order number?",
        "I don't have an order associated with that number.",
    ):
        assert check_unbacked_order_lookup(context, reply) is None, reply


def test_a_reply_may_talk_about_an_order_the_agent_really_read():
    context = OutputCheckContext(intent=Intent.REFUND_REQUEST, order_found=True)
    assert check_unbacked_order_lookup(context, "I've checked your order: it is paid.") is None


def test_ordinary_replies_that_mention_orders_in_passing_are_left_alone():
    for reply in (
        "Your refund request is with our team. Your ticket ID is 123.",
        "You can find your order number in the confirmation email we sent you.",
        "We checked your account and your Starter plan is active until November 6, 2026.",
        "I understand you'd like to cancel your order. A human will follow up with you.",
    ):
        assert check_unbacked_order_lookup(_NO_ORDER, reply) is None, reply




def _ctx(**kw):
    from app.schemas.guardrails import OutputCheckContext

    return OutputCheckContext(**kw)


def test_saying_an_order_was_cancelled_needs_the_return_step_to_have_done_it():
    from app.guardrails.output_checks import check_unbacked_order_action_claim

    said = "Done, your order has been cancelled."

    assert check_unbacked_order_action_claim(_ctx(), said).code == "unbacked_order_action_claim"
    assert check_unbacked_order_action_claim(_ctx(order_cancelled=True), said) is None
    assert check_unbacked_order_action_claim(_ctx(), "I can cancel it if you confirm.") is None


def test_saying_credits_were_added_needs_them_to_have_been_recorded():
    from app.guardrails.output_checks import check_unbacked_order_action_claim

    said = "$21.00 in credits have been added to your account."

    assert check_unbacked_order_action_claim(_ctx(), said).code == "unbacked_order_action_claim"
    assert check_unbacked_order_action_claim(_ctx(credits_added=True), said) is None
    # Describing the offer is not claiming it happened.
    assert check_unbacked_order_action_claim(_ctx(), "You could take $21.00 in credits added to your account.") is None


def test_a_refund_recorded_by_the_return_step_may_be_stated_and_otherwise_still_may_not():
    from app.guardrails.output_checks import check_unconfirmed_refund_claim

    said = "Your refund of $14.00 has been processed."

    assert check_unconfirmed_refund_claim(_ctx(), said).code == "unconfirmed_refund_claim"
    assert check_unconfirmed_refund_claim(_ctx(refund_recorded=True), said) is None


def test_an_offer_may_say_a_refund_will_be_given_but_not_that_it_was():
    from app.guardrails.output_checks import check_unconfirmed_refund_claim

    offering = _ctx(offering=True)

    assert check_unconfirmed_refund_claim(offering, "If you choose the refund, $14.00 will be refunded to your card.") is None
    assert check_unconfirmed_refund_claim(offering, "Your refund has been processed.").code == "unconfirmed_refund_claim"
    assert check_unconfirmed_refund_claim(_ctx(), "The refund will be refunded to your card.").code == "unconfirmed_refund_claim"


def test_describing_a_cancelled_order_in_general_is_not_a_claim_about_this_one():
    from app.guardrails.output_checks import check_unbacked_order_action_claim

    context = _ctx()

    assert check_unbacked_order_action_claim(context, "An order that was cancelled can't be returned.") is None
    assert check_unbacked_order_action_claim(context, "Your order has not shipped; it will be cancelled if you confirm.") is None
    assert check_unbacked_order_action_claim(context, "Hi, cancelled orders are not refunded.") is None
    assert check_unbacked_order_action_claim(context, "Your order is cancelled.").code == "unbacked_order_action_claim"
    assert check_unbacked_order_action_claim(context, "Tu pedido ha sido cancelado.").code == "unbacked_order_action_claim"
