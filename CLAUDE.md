# AcmeFlow AI Sales & Support Agent

Guidance for AI coding assistants (Claude Code, Gemini CLI) working in this repository. `GEMINI.md` just points here — keep everything in this file, don't fork the content.

## What this is

A portfolio project: a production-oriented AI Sales & Support Agent for a fictional SaaS product, **AcmeFlow**. It exists to demonstrate agent orchestration (LangGraph), RAG, typed tool calling, a deterministic business-rules layer, reproducible evaluation, and observability — not a chatbot wrapper. It will be public on GitHub and read by recruiters/interviewers, so code quality, commit hygiene, and documentation must be professional. Never fabricate test results, evaluation numbers, or claim something works without having run it.

The full spec this project is built from, and the agreed roadmap, live in this conversation's approved plan; ask the user if you need the original requirements restated.

## Collaboration model (important — respect this)

This project is being built by the repo owner with AI guidance, not built for them end-to-end. Per module:

- **Owner writes, AI guides closely (their learning focus):** the LangGraph agent graph (`backend/app/agent/`), the RAG pipeline (`backend/app/rag/`), and the evaluation suite (`backend/evaluation/`). For these, explain the design and trade-offs, review their code, but let them write it unless they ask otherwise.
- **AI writes, and explains why:** the frontend (`frontend/`, Vite + React) and the deterministic business-logic layer (`backend/app/business/`).
- **Shared/infra** (FastAPI skeleton, Docker, DB schema/migrations, tool wrappers, guardrails, observability wiring): scaffolded by AI as needed; the owner can claim any piece.

Always explain *why*, not just *what* — the owner needs to be able to defend every architectural decision in an interview.

The RAG pipeline (`backend/app/rag/`) is the one exception exercised so far: the owner explicitly asked for AI to write it (to reach the LangGraph agent stage sooner, their actual learning priority) instead of writing it themselves — see the Stage 3 PRs for the resulting code and its rationale.

## Architecture

- **Backend:** Python 3.12+, FastAPI, LangGraph, LangChain (chat-model + embeddings abstraction only — not used as a catch-all framework), Pydantic v2, SQLAlchemy + Alembic.
- **LLM provider abstraction:** LangChain chat models, supporting **Anthropic Claude**, **Google Gemini**, and **Ollama** (local, free, no API key — for offline dev) interchangeably via `LLM_PROVIDER` env var. No OpenAI dependency.
- **Embeddings:** Google `text-embedding-004` by default, or Ollama's `nomic-embed-text` (also 768-dim, no API key) via `EMBEDDING_PROVIDER`, behind the same swappable interface.
- **Database:** PostgreSQL + pgvector — plans, customers, subscriptions (a customer's commercial state, kept separate from identity so plan/status changes have history), KB documents + chunks, tickets, evaluation runs.
- **Frontend:** Vite + React SPA (no SSR/routing needs) with streaming responses, activity indicators, source references, customer selector, simulated checkout/escalation results.
- **Observability:** LangSmith tracing (graph/LLM/tool/retrieval spans + metadata) plus basic structured app logging.
- **Packaging:** Docker Compose (backend, frontend, Postgres+pgvector), `.env.example` — never commit `.env` or real API keys.

## Repo structure

```
backend/
  app/
    main.py          # FastAPI entry
    api/              # routers: chat, customers, evaluations, health
    core/             # config, llm provider abstraction (Claude/Gemini)
    agent/            # graph.py, state.py, nodes/, prompts/        [owner writes]
    rag/               # loaders, chunking, ingestion.py, retriever.py [AI writes, per owner's Stage 3 call]
    tools/             # typed tool wrappers (get_customer_context, etc.)
    business/          # upsell_rules.py, pricing.py, eligibility.py  [AI writes]
    db/                # models.py, session.py, seed.py
    guardrails/        # prompt-injection handling, output validation
    schemas/           # Pydantic: Intent, CustomerContext, ToolResult, AgentState...
  alembic/              # migrations (env.py wired to app.core.config)
  data/seed/            # plans.json, customers.json, kb/*.md (markdown KB docs, loaded by app.rag.ingestion)
  evaluation/           # dataset.jsonl, run_eval.py, metrics.py, llm_judge.py [AI writes, per owner's Stage 9 call]
  tests/                # unit/, integration/, evaluation/
frontend/               # Vite + React chat app                       [AI writes]
docker-compose.yml, Dockerfile(s), .env.example, README.md
```

## Core principles

1. Prefer deterministic Python for deterministic business decisions (upsell eligibility, pricing, plan limits) — the LLM never decides a fact a tool/function can compute.
2. Keep agent state explicit and strongly typed (Pydantic/TypedDict) — no ad-hoc dicts passed through the graph.
3. Keep tool inputs/outputs strongly typed.
4. Separate business logic from LLM prompts.
5. Make failures observable (LangSmith + structured logs), not silently swallowed.
6. Make evaluations reproducible — same dataset, same script, same metrics, every run.
7. Don't hide everything inside LangChain/LangGraph abstractions where a plain function is clearer.
8. Avoid unnecessary dependencies — don't introduce a technology just to pad the stack.
9. Keep the architecture understandable enough that the owner can explain every major component in an interview.

## Guardrails (non-negotiable)

Never invent product information, pricing, features, or limits. Never claim a refund was issued unless a tool confirms it. Never create a checkout unless eligibility was actually checked. Never expose internal system prompts. Handle prompt-injection attempts by refusing and continuing normally, without special-casing detection in a way that itself leaks the system prompt.

### Stage 7 status

`app/guardrails/` now has two modules, wired into the graph at three points — `input_guardrail_node` and `safety_judge_node` on the way in, `guardrail_node` between `response_writer` and `END`:

- `output_checks.py` — deterministic, state-grounded checks on the AI's response text. **BLOCK** severity (response is rewritten to a safe fallback, same message id, so the false claim never sits in conversation history) for: an implied refund confirmation when no refund tool exists; a checkout link with no `checkout_session` in state; a claimed support ticket (or ticket number) when `ticket_receipt` is `None`; a verbatim system-prompt leak. **FLAG** severity (recorded on `AgentState.guardrail_flags`, not rewritten — too heuristic to safely auto-correct) for speculative billing explanations on `billing_question`.
- `input_checks.py` — matches known prompt-injection shapes (instruction override, system-prompt extraction, code execution, DB manipulation, roleplay jailbreak) against the incoming message. `input_guardrail_node` uses the match to short-circuit the graph straight to `END` with a fixed refusal — `intent_router` (and its LLM call) never runs, so the payload never reaches the model at all. Detection stays intentionally narrow (the curated shapes above, not generic suspicious wording) precisely because a regex match is weaker evidence than a tool result, and an over-broad filter would refuse legitimate messages.
- **Input safety is a cascade, not a single check.** Anything the regex layer doesn't match still goes to `intent_router`, which now scores `safety_confidence` in the *same* structured-output call that classifies intent (free — no extra LLM round trip). Below `_SAFETY_CONFIDENCE_THRESHOLD` (0.7, in `app/agent/routing.py`), routing detours to `safety_judge_node`: a dedicated second LLM call, with a prompt focused only on that one decision, before anything else (retrieval, customer context, response writing) runs. Most conversations never reach it — that's the point of the cascade, paying for a closer look only when the cheap signal is genuinely unsure.

**Empirically, the middle tier under-triggers with `qwen2.5:7b-instruct`.** Live-tested a request (asked in Spanish) for step-by-step instructions to hack into someone else's database — a real misuse attempt that dodges every regex pattern (no SQL syntax, no classic jailbreak phrasing) — and `intent_router` still scored it `safety_confidence: 0.9`, above the 0.7 threshold, so `safety_judge_node` never ran. The request only got refused because `response_writer` declined it on its own (the same unenforced, model-dependent guarantee Stage 6 already flagged). The cascade's wiring is correct (unit-tested with mocked confidence values across both branches), but the threshold is an untuned guess — calibrating it needs labeled adversarial cases, which is exactly what Stage 9's evaluation dataset should provide, not something to hand-tune here without data.

The `fabricated_ticket_claim` check exists because of a violation caught live while building this stage, not a hypothesized one: a `billing_question` routes straight to `response_writer` (it never reaches `human_escalation`, so no ticket is ever created for it), and `qwen2.5:7b-instruct` still told a customer a ticket had been created, with a fabricated ID derived from their own UUID. The fix was verified against that exact captured response, not a synthetic one.

Response language consistency was fixed in the `response_writer` prompt directly (explicit "reply in the same language" instruction) rather than as a code guardrail — cheaper and more appropriate there, since it's not a falsifiable-from-state fact the way the BLOCK checks are.

Code execution and direct DB manipulation remain safe structurally, unchanged from Stage 6: no tool exists that runs arbitrary code or raw SQL, so there's no path from "the LLM says yes" to anything actually happening.

## Setup & commands

Backend:
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q          # tests
ruff check .        # lint
```

Full local stack:
```bash
cp .env.example .env   # fill in real API keys, never commit this file
docker compose up --build
curl http://localhost:8000/api/health
```

Database (after `docker compose up -d db`):
```bash
cd backend
alembic upgrade head        # apply migrations
python -m app.db.seed       # load plans + sample customers/subscriptions
python -m app.rag.ingestion # embed and load the KB (backend/data/seed/kb/*.md); requires the
                             # configured EMBEDDING_PROVIDER to be reachable (e.g. `ollama serve`)
```

Both `db.seed` and `rag.ingestion` write to tables the integration test suite clears as part of
its own setup/teardown (`tests/integration/test_db_seed.py`, `test_rag_ingestion.py`,
`test_retriever.py`) — re-run the relevant command after `pytest` if you need real data in the DB
again for manual testing.

## Environment variables

See `.env.example` for the full list. Key ones: `LLM_PROVIDER` (`anthropic` | `google` | `ollama`), `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OLLAMA_MODEL`/`OLLAMA_BASE_URL` (no key needed — requires `ollama pull qwen2.5:7b-instruct` + `ollama serve` running locally), `EMBEDDING_PROVIDER` (`google` | `ollama`), `OLLAMA_EMBEDDING_MODEL` (requires `ollama pull nomic-embed-text`), `DATABASE_URL`, `LANGCHAIN_API_KEY`/`LANGCHAIN_TRACING_V2` for LangSmith.

The `db` service in `docker-compose.yml` publishes on host port **5433** (not 5432), to avoid colliding with a native Postgres install. `DATABASE_URL` in `.env.example` already points at 5433; containers talk to each other over the internal Docker network on the default 5432, unaffected by this.

## Testing conventions

Unit tests for business logic and tool validation; integration tests for the API, the DB layer, the agent graph, and RAG retrieval; evaluation tests run against the fixed dataset in `backend/evaluation/`. Don't chase 100% coverage — prioritize the behavior described in the spec (upsell decisions, guardrails, escalation).

DB integration tests (`backend/tests/integration/test_db_*.py`) need a real Postgres with the schema already migrated — run `docker compose up -d db && alembic upgrade head` first. pgvector's column type has no SQLite equivalent, so these can't run against an in-memory DB; CI runs a `pgvector/pgvector:pg16` service container for this.

**Testing philosophy — spec-first, TDD where it fits:**
- **Spec before code, per module.** Before implementing a module (agent nodes, RAG retriever, a new tool), nail down its interface first — Pydantic schemas, function signatures, expected inputs/outputs — then implement against that.
- **TDD for deterministic code.** Business rules, pricing, eligibility, tools, and the DB layer are pure functions with clear input/output pairs — write the test first for these.
- **Mocked-LLM tests for the graph.** LangGraph routing and state transitions should be tested with a mocked/stubbed LLM response, asserting on deterministic control flow (which node ran, what state looks like) — not on real model output.
- **Don't force TDD onto raw LLM output.** Judging actual model output quality (is the answer correct, grounded, non-hallucinated) belongs to the evaluation suite, not unit tests — trying to unit-test non-deterministic generations produces flaky, meaningless tests.

## Git workflow

- **Every unit of work is a branch + PR into `main`, no exceptions** — including the initial bootstrap (PR #1). `main` started as a single empty root commit specifically so a PR could target it from the first change.
- **Target ~200-300 changed lines per PR, 400 as a hard ceiling — starting with Stage 1.** This follows the Cisco/SmartBear code-review study (also cited in Google's internal practices): review defect-detection effectiveness drops sharply past ~200-400 lines of diff, because nobody reviews a bigger diff carefully. Generated/boilerplate content (Alembic migrations, framework scaffolding, lockfiles) doesn't count toward the budget — it isn't reviewed line by line. PR #1 (bootstrap) is exempt: it's foundational scaffolding with nothing to split against, not ongoing feature work.
- **Default to one PR per roadmap stage below**, merged only once CI is green. Adjust when it genuinely helps:
  - Combine stages into one PR when splitting them would be artificial and the combined diff still fits the budget (e.g. Business rules + Tools layer, since tools mostly wrap that logic).
  - When a stage would blow past ~400 real lines (RAG, the agent graph, and Frontend are the likely candidates), split it into a **PR chain (stacked PRs)** instead of one big PR: PR A merges into `main`, PR B branches off A and targets A's branch (not `main`), PR C branches off B and targets B's branch, and so on — each individual PR stays reviewable, merged in order once its base has landed.
- PR titles/descriptions should read like real engineering work: what changed, why, how it was verified (tests run, manual check) — not "Stage N done."
- Prefer squash-merge so `main` history stays one commit per logical unit of work, matching the roadmap checklist below.

## Roadmap status

Tests are not a separate stage — per the TDD philosophy above, each stage ships its own tests in the same PR.

- [x] Stage 0 — Repo bootstrap (backend skeleton, Docker Compose, health check)
- [x] Stage 1 — DB schema + seed data
- [x] Stage 2 — LLM provider abstraction (Claude + Gemini + Ollama) + LangSmith tracing wired from day one (near-free via env vars — gives trace visibility during the hardest debugging stages below)
- [x] Stage 3 — RAG pipeline (AI-written per owner's call — see "Collaboration model" above; KB loader, section/fixed-size chunking, ingestion, pgvector retrieval)
- [x] Stage 4 — Business rules layer
- [x] Stage 5 — Tools layer (wraps business rules, RAG, DB)
- [x] Stage 6 — LangGraph agent (owner-written)
- [x] Stage 7 — Guardrails
- [x] Stage 8 — FastAPI chat endpoint (streaming) + trace metadata tagging (customer_id, conversation_id, intent, env, model, app_version)
- [x] Stage 9 — Evaluation dataset + script (AI-written per owner's call, like Stage 3 — the owner reviewed the design and the dataset; see `backend/evaluation/README.md` for methodology and known limitations) — run against the real API before the frontend exists, so agent quality is validated before UI polish
- [ ] Stage 10 — Frontend chat UI
- [ ] Stage 11 — README, diagrams, demo scenarios, polish

Update this checklist as stages complete.
