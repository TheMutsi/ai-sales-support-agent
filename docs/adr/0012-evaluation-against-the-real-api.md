# ADR-0012: Evaluate the running API with a dev set, a held-out set and mostly deterministic metrics

- **Status:** Accepted
- **Introduced in:** PRs #36-#39 and #41 (Stage 9); held-out set and judge model in PR #46;
  Langfuse experiments in PRs #50-#51; trials and paired comparison in PR #53

## Context

Unit tests pin control flow with a stubbed model; they say nothing about whether
answers are right. The agent's quality depends on prompts, retrieval and a
non-deterministic model, and every fix made after reading failures risks tuning to
those exact cases.

## Decision

- **Black-box over HTTP.** `run_eval` sends each case to the running `/api/chat`
  and scores what a client would receive: the response text plus the typed `done`
  summary. It exercises the real graph, guardrails, streaming and database, with no
  test-only path through the code.
- **Structural metrics come from state, not text.** Intent, escalation, ticket
  creation, input blocking and upgrade eligibility are read from `ChatTurnSummary`
  (ADR-0010), so they are exact.
- **Text metrics are deterministic first.** `must_include` / `must_not_include`
  substring checks, with their negation-blindness pinned by a unit test.
- **One LLM judge, for the case substrings cannot handle**: whether a forbidden claim
  is asserted or denied. The judge model is injected and should differ from the
  agent's (`--judge-model`), because a model shares its own blind spots.
- **Two datasets.** `dataset.jsonl` (dev, 55 cases) may drive fixes, so its numbers
  are optimistic by construction. `heldout.jsonl` (16 cases) is never edited or tuned
  on, and a test keeps the sets disjoint. The gap between them is the honest
  measure of generalization.
- **Errors are not passes.** A case that fails to run or score is listed separately
  and excluded from every rate.
- **Comparisons are statistical, not eyeballed.** `--trials k` runs every case k
  times and reports `pass^k` (cases passing all k trials, the reliability measure
  from tau-bench); every rate carries a Wilson 95% interval; `--baseline` pairs
  cases against an earlier report and gives an exact McNemar p-value on the ones
  that flipped.
- **Two backends, one scorer.** `local` writes a JSON report; `langfuse` runs the
  same cases as a Langfuse dataset experiment, so runs can be compared side by side
  in its UI. The JSONL files stay the source of truth either way.
- **Reports include the safety threshold sweep**, the data the routing threshold is
  set from (ADR-0007).
- Evaluators are pure `(case, turn) -> MetricResult | None` functions; adding one is
  a function plus a list entry.

## Consequences

- Numbers reflect what a customer would see, including guardrail rewrites.
- Retrieval quality and tool selection are not measured: they are not visible from
  the HTTP API, and they are not approximated from text. That would need trace
  inspection.
- Results move between runs (the model is not run at temperature 0), and per-metric
  samples are small. At this dataset size only differences of roughly 15 points or
  more stand out from noise; smaller ones need more trials or a targeted probe.
- A held-out set is spent once its failures have been read and acted on; it then
  needs replacing before it can be trusted again.
- Running the suite needs the whole stack: database seeded, KB ingested, API and
  model up.

## Alternatives

- **Call the graph in-process.** Faster, but skips the API contract, streaming and
  correction path a real client depends on.
- **LLM judge for everything.** Flexible, but turns every metric into a
  non-deterministic opinion and hides exact structural failures.
- **A single dataset.** Simpler, and unable to tell improvement from overfitting.

## References

- `backend/evaluation/` and its `README.md` (methodology, results, known limitations)
- `backend/app/schemas/chat.py` (`ChatTurnSummary`)
