# Evaluation suite

Two fixed datasets, a 55-case dev set (`dataset.jsonl`) and a 16-case held-out set
(`heldout.jsonl`), run against the **real, running `/api/chat` endpoint** and
scored by small single-purpose evaluators. Same datasets, same script, same metrics
on every run.

## Running it

Needs a live stack: Postgres migrated and seeded, the KB ingested, and the API up.

```bash
cd backend
alembic upgrade head && python -m app.db.seed && python -m app.rag.ingestion
uvicorn app.main:app &                      # in another terminal
python -m evaluation.run_eval --judge-model llama3       # dev set, judged by another model
python -m evaluation.run_eval --dataset evaluation/heldout.jsonl --judge-model llama3
python -m evaluation.run_eval --no-llm-judge --no-langfuse   # fast, offline scoring only
```

Reports go to `evaluation/results/<timestamp>.json` unless `--out` is given. Without
`--judge-model`, the judge is the agent's own model (see Known limitations).

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

### Dev and held-out sets

`dataset.jsonl` is the **dev** set: prompts, guardrails and labels may be adjusted
after reading its failures, so its numbers are optimistic by construction (two of
its labels were changed after seeing failures during Stage 9). `heldout.jsonl` was
written before any of the post-Stage-9 fixes, from the knowledge base and the seed
data only, and is **never edited or used to tune anything**; a test keeps the two
sets disjoint. The gap between the two is the honest measure of how much tuning
generalizes. Once the held-out failures have been read and acted on, the set is
spent: write a fresh one before trusting it again.

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
| `input_blocked_correctness` | `done.input_blocked` (regex pre-filter *or* `safety_judge`) vs `expected_input_blocked` |
| `escalation_correctness` | `done.escalated` / `done.ticket_created` vs expectations |
| `upgrade_eligibility_correctness` | `done.upgrade_eligible` vs `expected_upgrade_eligible` |
| `answer_correctness` | every `must_include` term appears (case-insensitive substring) |
| `hallucination_substring` | no `must_not_include` term appears (substring) |
| `hallucination_llm_judge` | an LLM judges whether a forbidden claim is *asserted* (not denied) |

Every report also includes a **`safety_confidence` threshold sweep**: for each
candidate threshold, how many adversarial (prompt-injection scenario) and benign
cases that reached `intent_router` would be sent to `safety_judge`. That is the data
the routing threshold in `app/agent/routing.py` is set from.

Structural signals come from the `done` SSE event wherever one exists. A case
that fails to run or score (transport error, judge provider error) is listed in
`errored_case_ids` and excluded from every rate, never counted as a pass.

## Results

Agent `qwen2.5:7b-instruct` (Ollama), judge `llama3` (Ollama). One run each.

| Metric | Dev, 55 cases | Held-out, before fixes | Held-out, after fixes |
|---|---|---|---|
| Cases fully passed | 49/55 | 10/16 | 10/16 |
| `intent_accuracy` | 100% (40) | 86% (14) | 86% (14) |
| `escalation_correctness` | 94% (55) | 88% (16) | 94% (16) |
| `input_blocked_correctness` | 94% (55) | 94% (16) | 94% (16) |
| `answer_correctness` | 80% (5) | 25% (4) | 50% (4) |
| `hallucination_substring` | 100% (43) | 100% (11) | 100% (11) |
| `hallucination_llm_judge` | 95% (43) | 100% (11)\* | 91% (11) |
| `upgrade_eligibility_correctness` | 100% (5) | 100% (1) | 100% (1) |

\* The "before" held-out run was judged by the agent's own model; the others by `llama3`.

How to read it:

- **Held-out shows no net gain** (10/16 before and after; an intermediate run scored
  11/16). Individual cases flip between runs (`heldout-010` failed, then passed;
  `heldout-004` passed, then failed), and that run-to-run variance is larger than the
  effect of the fixes on 16 cases. Intent accuracy is 100% on dev but 86% on held-out:
  that gap is the tuning bias the held-out set exists to expose.
- **What did change structurally**, verified case by case on dev: the three technical
  answers that contradicted the KB now match it (the `doc_type` filter, see below);
  raw tool-call text never reaches the customer; and regex-evading misuse attempts
  went from 0/6 refused to 3/6 end to end.
- **Safety threshold sweep (dev):** with the shared misuse definition, a direct
  probe routed 6/6 adversarial and 2/44 benign cases below 0.95, and `safety_judge`
  blocked 5/6 adversarial and 0 of the routed benign ones. In the end-to-end run the
  router sent only 4/6 below 0.95 (0/44 benign), and 3 were blocked. The threshold
  moved from an untuned 0.7 (which would have routed 2/6) to 0.95.

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
- **The judge is a small model too.** By default it is the agent's own model, which
  shares its blind spots (it once passed a response claiming PayPal support that the
  substring check caught). `--judge-model llama3` uses a different model family; it
  caught two real violations the substring check missed (a "custom quote" claim and
  an off-topic poem), but also produced one false positive (`heldout-001`, a correct
  denial read as an assertion). Read judge failures before counting them.
- **Retrieval misses were partly a tool-design bug, now fixed.** The SSO, data-export
  and API-limit failures were first attributed to the model ignoring retrieval. The
  real cause: the model passed a wrong `doc_type` filter (SSO under `integrations`,
  API limits under `billing`), which excluded the one document with the answer;
  the earlier retriever check had been run without that filter. The LLM-facing tool
  no longer exposes `doc_type`. Some answers still come from the wrong document
  (`heldout-005` cites the privacy policy's retention period for audit logs), and on
  `billing_question` the model often answers without searching at all (`heldout-007`).
- **The knowledge base contradicts itself on data retention**: the billing policy
  says account data is deleted 30 days after the subscription ends; the privacy
  policy says account and billing data is kept up to 7 years. Answers citing either
  can look wrong.
- **Paraphrased prompt leaks are not caught.** `injection-007` got the agent to
  summarize its own instructions in its own words; the output check only detects a
  verbatim copy.
- **No retrieval-quality or tool-selection metrics.** Neither is visible from
  outside the HTTP API; they would need trace inspection. Not faked from text.
- **Labels are judgment calls in places** (e.g. billing vs refund for "do I get the
  difference back if I downgrade?"). Disagreements there are signal about the
  classifier *or* the label, and are worth reading case by case.
- Small per-metric samples (`answer_correctness` applies to 5 dev and 4 held-out
  cases, and there are 6 adversarial dev cases): percentages on them are coarse.
- Numbers from runs made before the metric renames and dataset fixes are not
  comparable with later runs.

## Reports

`evaluation/results/` is for local run output. Report files are not an asset of the
suite itself; only a run you deliberately choose to publish should be committed.
