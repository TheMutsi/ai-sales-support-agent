# Evaluation suite

A fixed 50-case golden dataset (`dataset.jsonl`) run against the **real, running
`/api/chat` endpoint**, scored by small single-purpose evaluators. Same dataset,
same script, same metrics on every run.

## Running it

Needs a live stack: Postgres migrated and seeded, the KB ingested, and the API up.

```bash
cd backend
alembic upgrade head && python -m app.db.seed && python -m app.rag.ingestion
uvicorn app.main:app &                      # in another terminal
python -m evaluation.run_eval               # report -> evaluation/results/<timestamp>.json
python -m evaluation.run_eval --no-llm-judge --no-langfuse   # fast, offline scoring only
```

If Langfuse tracing is enabled, each metric is also pushed as a score
(`eval.<metric>`) on the case's session (`conversation_id`), visible under the
trace/session in the Langfuse UI. These are API-pushed scores, **not** entries in
Langfuse's "Evaluators" tab (that tab configures server-side judges in the UI).

## Dataset

Each line is an `EvalCase` (`evaluation/schemas.py`): scenario, customer,
messages, and the expectations to check. Scenarios, metrics and intents are
`StrEnum`s, so a typo in the dataset fails at load time instead of silently
scoring wrong; duplicate case ids are rejected too. 12 scenarios: product,
pricing, billing, technical, upgrade, refund, human escalation, unsupported,
prompt injection, ambiguous input, wrong customer assumption, tool edge cases.

Customers are referenced by email; `run_eval.py` resolves all of them to ids in
one query before the run starts (ids change on every reseed), and fails fast if
any is missing.

## Layout

| Module | Responsibility |
|---|---|
| `schemas.py` | Typed contracts: dataset row, metric/case results, report |
| `dataset.py` | Loads `dataset.jsonl` with strict validation |
| `metrics.py` | Pure deterministic evaluators and pass-rate aggregation |
| `llm_judge.py` | The one evaluator that calls a model |
| `chat_client.py` | `/api/chat` client: SSE parsing into a typed `ChatTurn` |
| `run_eval.py` | Orchestration: customer lookup, run loop, Langfuse publishing, report |

`evaluation` depends on `app` (it reuses `Intent`, `ChatMessage` and the
`ChatTurnSummary` contract of the `done` event), never the other way around.

## Evaluators (`metrics.py`, `llm_judge.py`)

Each is a function `(case, turn) -> MetricResult | None`, where `turn` is the
final response text plus the typed `ChatTurnSummary`; `None` means "not
applicable to this case". Adding one = one function + one entry in
`DEFAULT_EVALUATORS`.

| Metric | How it is checked |
|---|---|
| `intent_accuracy` | `done.intent` == `expected_intent` |
| `input_blocked_correctness` | `injection_signal:*` guardrail flag vs `expected_input_blocked` |
| `escalation_correctness` | `done.escalated` / `done.ticket_created` vs expectations |
| `upgrade_eligibility_correctness` | `done.upgrade_eligible` vs `expected_upgrade_eligible` |
| `answer_correctness` | every `must_include` term appears (case-insensitive substring) |
| `hallucination_substring` | no `must_not_include` term appears (substring) |
| `hallucination_llm_judge` | an LLM judges whether a forbidden claim is *asserted* (not denied) |

Structural signals come from the `done` SSE event wherever one exists. A case
that fails to run or score (transport error, judge provider error) is listed in
`errored_case_ids` and excluded from every rate, never counted as a pass.

## Known limitations (read before trusting a number)

- **Non-deterministic.** The LLM is not run at temperature 0 here and results move
  between runs: two consecutive runs of the same dataset flipped `product-001` and
  `technical-002` (text-based checks). Structural metrics (input blocked, upgrade
  eligibility) were stable. Treat a single run as one sample, not a score.
- **Substring checks are negation-blind.** "We are *not* SOC 2 certified" contains
  "SOC 2". That is why the LLM judge exists; the substring check is kept (and its
  limitation pinned by a unit test) as the cheap deterministic first pass, and
  forbidden terms are written as assertions ("we are SOC 2") rather than bare
  topics where possible.
- **English only.** Every case is in English, so the response-language
  consistency of the agent is not covered.
- **The judge is the same model as the agent** (`get_chat_model()`), so it can
  share the agent's blind spots. This is observed, not theoretical: in one run it
  passed a response claiming PayPal and Apple Pay support, which the KB never
  mentions (the substring check caught it). A different/stronger judge model would
  be better.
- **Generation can ignore correct retrieval.** With `qwen2.5:7b-instruct`, some
  technical answers contradict the knowledge base even when the tool ran and
  retrieval ranked the right chunk first (checked by querying the retriever
  directly). The `answer_correctness` failures on SSO setup and data export are
  this model limitation, not a retrieval bug. Each case's report entry keeps its
  full turn summary (`tool_call_rounds`, `guardrail_flags`) to tell the two apart.
- **No retrieval-quality or tool-selection metrics.** Neither is visible from
  outside the HTTP API; they would need trace inspection. Not faked from text.
- **Labels are judgment calls in places** (e.g. billing vs refund for "do I get the
  difference back if I downgrade?"). Disagreements there are signal about the
  classifier *or* the label, and are worth reading case by case.
- Small per-metric samples (`answer_correctness` applies to 5 cases): percentages
  on them are coarse.
- Numbers from runs made before the metric renames and dataset fixes are not
  comparable with later runs.

## Reports

`evaluation/results/` is for local run output. Report files are not an asset of the
suite itself; only a run you deliberately choose to publish should be committed.
