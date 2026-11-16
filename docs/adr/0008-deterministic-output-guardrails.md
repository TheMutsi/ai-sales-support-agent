# ADR-0008: Output guardrails are deterministic checks against state

- **Status:** Accepted
- **Introduced in:** PRs #20-#21 (Stage 7); extended in PRs #33, #43, #48

## Context

Even with the right data in its context, a small model sometimes states things that
are false: during Stage 7 it told a customer a support ticket had been created, with
an ID derived from their own UUID, on a path that never creates tickets. Prompts
reduce that; they do not prevent it.

## Decision

`guardrail_node` runs after `response_writer` on every path that produces an answer,
and checks the text against what the graph actually did. Each check is a function
`(OutputCheckContext, response_text) -> GuardrailViolation | None` registered in one
tuple, `_ALL_CHECKS`.

- **BLOCK** when state proves the claim false: a refund confirmation (no refund tool
  exists), a checkout link without a `checkout_session`, a ticket claim without a
  `ticket_receipt`, a claim of having consulted the documentation when no search
  ran, a claim of having reviewed invoices or billing history (no tool exposes
  them), raw tool-call text, or a verbatim copy of the system prompt.
- **FLAG** when the signal is heuristic, such as a speculative explanation on a
  billing question. Recorded in `guardrail_flags` and in traces, not rewritten.
- **A blocked answer is replaced, not appended to.** The fallback reuses the original
  message `id`, so the `add_messages` reducer overwrites it and the false claim never
  stays in conversation history. If a real ticket exists, the fallback cites its real
  ID.
- Checks are regular expressions in English and Spanish, kept specific to claims
  rather than topics, so a correct denial ("we can't issue refunds here") passes.

### Check by check

Each check is there because of a reply that was seen, live or in the evaluation suite:

- `unconfirmed_refund_claim` (BLOCK): no tool issues a refund. Only past-tense claims count when
  the reply presents an offer ("will be refunded" is the offer), and a refund the return step
  recorded this turn, or an order already shows, is allowed.
- `unbacked_order_action_claim` (BLOCK): only the return step cancels orders or adds credits.
- `checkout_without_eligibility` (BLOCK): a checkout link needs a real `checkout_session`.
- `system_prompt_leak` (BLOCK): the prompt is a fixed string we own, so a long verbatim piece of
  it in a reply is a leak, not agreement.
- `fabricated_ticket_claim` (BLOCK): found live in Stage 6, a billing answer claimed a ticket with
  an id made from the customer's UUID. A ticket number cited in either word order counts, and a
  reply may quote only the conversation's own `MF-` number.
- `unverified_lookup_claim` (BLOCK): "I checked our documentation" with no search this turn
  (`tool_call_rounds` is 0). It needs an explicit documentation object, because a bare "I've
  checked" also covers true statements about the account.
- `fabricated_billing_history_claim` (BLOCK): first-person claims of having reviewed invoices,
  charges or payment history. No tool reads them.
- `internal_tool_text` (BLOCK): tool identifiers or "tool_call" written into the text, a search
  narrated but never run.
- `unverified_billing_explanation` (FLAG): speculation about why a charge happened. Hedging can
  look the same, so it is only recorded.
- `ungrounded_invoice_claim` (FLAG): found while recording the demo. A billing answer that talks
  about invoices without a search this turn, unless it admits it cannot see them (a negation then
  an access word; "doesn't" is not taken as one, so "the system doesn't have X" stays a claim).
  Known gap: an admission followed by an invented detail; evaluation cases billing-007 and
  billing-008 measure it.
- `unbacked_order_lookup` (BLOCK): found by the evaluation (order-010 to order-012). Outside
  `order_status`, asking for an order number (a verb that asks shortly before the noun; a bare
  "order number" is not a request), claiming an order was checked, or saying there is none.
  Known false positive: an escalation that tells the customer to give their number to support.
- `sensitive_data_exposure` (BLOCK): an internal UUID, an email other than the company's
  (`@mewflow.example`, which the knowledge base publishes), a phone number or a government id.
  Phone shapes are only those that cannot be an order id, a price or a date. Order numbers are
  allowed: they are the one identifier a signed-in customer is meant to receive.

The input checks only tag known attack shapes and never block by themselves; the node decides
what a tag means, and the evaluation reads the same tags.

## Consequences

- The guarantees in `CLAUDE.md` ("never claim a refund was issued unless a tool
  confirms it", "never create a checkout unless eligibility was checked") are
  enforced in code, not only requested in the prompt.
- Adding a check is one function and one tuple entry, tested without the graph
  (ADR-0003).
- Regex checks miss paraphrases. The prompt-leak check catches a verbatim copy but
  not the model summarizing its own instructions (seen in the evaluation dev set).
- A false positive replaces a correct answer with a generic fallback. That is why
  heuristic signals are FLAG, not BLOCK.
- Because tokens stream before this check runs, a blocked answer is corrected after
  the client has seen it (ADR-0010).

## Alternatives

- **An LLM judge on every answer.** Catches paraphrases, but doubles cost, and its
  verdict is itself unverified.
- **Prompt instructions only.** Already in place; the fabricated-ticket case is the
  evidence they are not enough.

## References

- `backend/app/guardrails/output_checks.py`, `backend/app/schemas/guardrails.py`
- `backend/app/agent/nodes/guardrail.py`
