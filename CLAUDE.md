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

## Architecture

- **Backend:** Python 3.12+, FastAPI, LangGraph, LangChain (chat-model + embeddings abstraction only — not used as a catch-all framework), Pydantic v2, SQLAlchemy + Alembic.
- **LLM provider abstraction:** LangChain chat models, supporting **Anthropic Claude** and **Google Gemini** interchangeably via `LLM_PROVIDER` env var. No OpenAI dependency.
- **Embeddings:** Google `text-embedding-004` by default, behind the same swappable interface.
- **Database:** PostgreSQL + pgvector — customers/plans, KB documents + chunks, tickets, evaluation runs.
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
    rag/               # loaders, chunking, ingestion.py, retriever.py [owner writes]
    tools/             # typed tool wrappers (get_customer_context, etc.)
    business/          # upsell_rules.py, pricing.py, eligibility.py  [AI writes]
    db/                # models.py, session.py, alembic/
    guardrails/        # prompt-injection handling, output validation
    schemas/           # Pydantic: Intent, CustomerContext, ToolResult, AgentState...
  data/                 # seed KB docs, seed customers/plans
  evaluation/           # dataset.jsonl, run_eval.py, metrics.py       [owner writes]
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

## Environment variables

See `.env.example` for the full list. Key ones: `LLM_PROVIDER` (`anthropic` | `google`), `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `DATABASE_URL`, `LANGCHAIN_API_KEY`/`LANGCHAIN_TRACING_V2` for LangSmith.

## Testing conventions

Unit tests for business logic and tool validation; integration tests for the API, the agent graph, and RAG retrieval; evaluation tests run against the fixed dataset in `backend/evaluation/`. Don't chase 100% coverage — prioritize the behavior described in the spec (upsell decisions, guardrails, escalation).

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
- [ ] Stage 1 — DB schema + seed data
- [ ] Stage 2 — LLM provider abstraction (Claude + Gemini) + LangSmith tracing wired from day one (near-free via env vars — gives trace visibility during the hardest debugging stages below)
- [ ] Stage 3 — RAG pipeline (owner-written)
- [ ] Stage 4 — Business rules layer
- [ ] Stage 5 — Tools layer (wraps business rules, RAG, DB)
- [ ] Stage 6 — LangGraph agent (owner-written)
- [ ] Stage 7 — Guardrails
- [ ] Stage 8 — FastAPI chat endpoint (streaming) + trace metadata tagging (customer_id, conversation_id, intent, env, model, app_version)
- [ ] Stage 9 — Evaluation dataset + script (owner-written) — run against the real API before the frontend exists, so agent quality is validated before UI polish
- [ ] Stage 10 — Frontend chat UI
- [ ] Stage 11 — README, diagrams, demo scenarios, polish

Update this checklist as stages complete.
