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
