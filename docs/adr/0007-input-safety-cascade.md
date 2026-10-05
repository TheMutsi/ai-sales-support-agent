# ADR-0007: Input safety is a three-tier cascade

- **Status:** Accepted
- **Introduced in:** PRs #20-#22 (Stage 7); recalibrated in PRs #45, #47 and #49

## Context

Users will try to make the agent ignore its rules, leak its prompt, act on someone
else's account, or produce harmful content. A dedicated LLM safety check on every
message doubles the cost and latency of every turn. A regex filter alone is cheap
but only catches phrasings someone thought of in advance.

## Decision

Three tiers, each paid for only when the previous one is unsure:

1. **`input_guardrail` (regex, free).** Narrow, curated attack shapes (instruction
   override, prompt extraction, code execution, SQL, roleplay jailbreak) in English
   and Spanish. A match ends the run with a fixed refusal: no LLM ever sees the
   payload. Kept narrow on purpose, because a regex is weak evidence and a broad one
   refuses legitimate customers.
2. **`intent_router`'s `safety_confidence` (free).** Scored in the same structured
   call that classifies intent, so it adds no round trip.
3. **`safety_judge` (one extra LLM call).** Runs when `safety_confidence` is below
   `_SAFETY_CONFIDENCE_THRESHOLD`, and **always for `unsupported`**, with a prompt
   focused on that one decision, before any customer data or retrieval is touched.
   `unsupported` is the class misuse lands in when it is not a recognizable support
   request, and its route opens a support ticket, a side effect; the dev set caught
   phishing and other-customer-data requests scored 0.95-1.0, classified
   `unsupported`, that the judge blocks in isolation.

Tiers 2 and 3 share one `MISUSE_DEFINITION` (`app/agent/prompts/safety_policy.py`),
so the cheap score and the careful check cannot drift apart on what they look for.

The threshold is **0.95, set from data**. It started as an untuned 0.7. The
evaluation dev set showed the real problem was the definition, not the number: both
LLM tiers scored every regex-evading attempt as safe because "unsafe" was defined
too narrowly. With the shared, broader definition, the threshold sweep moved it to
0.95. Numbers and caveats are in `backend/evaluation/README.md`.

## Consequences

- Most legitimate messages pay nothing extra.
- After the shared definition and the 0.95 threshold, 3 of 6 regex-evading dev
  attempts were refused end to end (was 0 of 6), with no legitimate message refused.
  After routing `unsupported` to the judge and one more regex phrasing, PR #49
  reports `input_blocked_correctness` at 100% on the dev set. That is the set these
  fixes were made from; the held-out set is the honest check. Whatever still gets
  through meets structural limits: no tool runs code or SQL, refunds have no tool,
  and output checks run on every answer (ADR-0008).
- The router scores almost every message 0.9 or 1.0, so the threshold sits in a
  narrow band. It is model-specific and must be re-swept after a model change
  (`run_eval` reports the sweep on every run).
- `safety_confidence` is hidden from API clients in production, because it would let
  someone rephrase until the score goes up. It stays in traces.

## Alternatives

- **LLM judge on every message.** Simplest to reason about, double the cost.
- **Broad keyword filtering.** Cheap, but refuses real customers who say "ignore"
  or "database".
- **Rely on the response writer refusing on its own.** It often does, but that is a
  model behavior, not a guarantee.

## References

- `backend/app/guardrails/input_checks.py`, `backend/app/agent/nodes/input_guardrail.py`
- `backend/app/agent/nodes/safety_judge.py`, `backend/app/agent/prompts/safety_policy.py`
- `backend/app/agent/routing.py` (`_SAFETY_CONFIDENCE_THRESHOLD`)
