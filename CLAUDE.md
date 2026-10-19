# MewFlow AI Sales & Support Agent

Guidance for AI coding assistants (Claude Code, Gemini CLI) working in this repository. `GEMINI.md` just points here — keep everything in this file, don't fork the content.

## What this is

A portfolio project: a production-oriented AI Sales & Support Agent for a fictional SaaS product, **MewFlow**. It exists to demonstrate agent orchestration (LangGraph), RAG, typed tool calling, a deterministic business-rules layer, reproducible evaluation, and observability — not a chatbot wrapper. It will be public on GitHub and read by recruiters/interviewers, so code quality, commit hygiene, and documentation must be professional. Never fabricate test results, evaluation numbers, or claim something works without having run it.

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
- **Frontend:** an embeddable chat widget named **Mew**, compiled to one script (`mew.js?key=<public api key>`), isolated in an iframe, with a queue-style global (`Mew('open')`, `show`, `hide`, `close`), a 24 hour conversation window shared across tabs, an unread badge, sound, and typed message parts (text, image, link now; cards and carousels later). The shop's server signs a short-lived token for its logged-in customer; anonymous visitors can ask knowledge-base questions and identify with an emailed code. Replaces the Vite + React SPA planned at the start; see `docs/adr/0014-conversation-anchored-identity-with-scopes.md` and `docs/adr/0015-embeddable-widget-in-an-iframe.md`. The fictional product is **MewFlow** (renamed from AcmeFlow in Stage 10; the widget is **Mew**).
- **Observability:** self-hosted Langfuse tracing (graph/LLM/tool/retrieval spans + metadata) plus basic structured app logging. Replaced the planned LangSmith in Stage 8, see `docs/adr/0011-self-hosted-langfuse-for-tracing.md`.
- **Packaging:** Docker Compose (backend, frontend, Postgres+pgvector), `.env.example` — never commit `.env` or real API keys.

## Repo structure

```
backend/
  app/
    main.py          # FastAPI entry
    api/              # routers: chat, customers, evaluations, health
    core/             # config, llm provider abstraction (Claude/Gemini)
    agent/            # graph.py, state.py, nodes/, prompts/, permissions.py  [owner writes]
    auth/             # scopes, tokens, login, one-time codes, conversations
    chat/             # a conversation's stored messages, one turn at a time
    orders/            # OrderSource interface + simulated source (the shop's orders API stand-in)
    rag/               # loaders, chunking, ingestion.py, retriever.py [AI writes, per owner's Stage 3 call]
    tools/             # typed tool wrappers (get_customer_context, etc.)
    business/          # upsell_rules.py, pricing.py, eligibility.py  [AI writes]
    db/                # models.py, session.py, seed.py
    guardrails/        # prompt-injection handling, output validation
    schemas/           # Pydantic: Intent, CustomerContext, ToolResult, AgentState...
  alembic/              # migrations (env.py wired to app.core.config)
  data/seed/            # plans.json, customers.json, kb/*.md (markdown KB docs, loaded by app.rag.ingestion)
  evaluation/           # dataset.jsonl (dev), heldout.jsonl, run_eval.py, metrics.py, llm_judge.py [AI writes, per owner's Stage 9 call]
  tests/                # unit/, integration/, evaluation/
frontend/               # Mew widget: Vite + React, one script mew.js [AI writes]
backoffice/             # the back office: Vite + React app over /api/admin (placeholder login, ADR-0016) [AI writes]
docs/                   # architecture.md (diagrams) and adr/ (architecture decision records)
docker-compose.yml, Dockerfile(s), .env.example, README.md
```

## Core principles

1. Prefer deterministic Python for deterministic business decisions (upsell eligibility, pricing, plan limits) — the LLM never decides a fact a tool/function can compute.
2. Keep agent state explicit and strongly typed (Pydantic/TypedDict) — no ad-hoc dicts passed through the graph.
3. Keep tool inputs/outputs strongly typed.
4. Separate business logic from LLM prompts.
5. Make failures observable (Langfuse traces + structured logs), not silently swallowed.
6. Make evaluations reproducible — same dataset, same script, same metrics, every run.
7. Don't hide everything inside LangChain/LangGraph abstractions where a plain function is clearer.
8. Avoid unnecessary dependencies — don't introduce a technology just to pad the stack.
9. Keep the architecture understandable enough that the owner can explain every major component in an interview.

## Guardrails (non-negotiable)

Never invent product information, pricing, features, or limits. Never claim a refund was issued unless a tool confirms it. Never create a checkout unless eligibility was actually checked. Never expose internal system prompts. Handle prompt-injection attempts by refusing and continuing normally, without special-casing detection in a way that itself leaks the system prompt.

### Stage 7 status

`app/guardrails/` now has two modules, wired into the graph at three points — `input_guardrail_node` and `safety_judge_node` on the way in, `guardrail_node` between `response_writer` and `END`:

- `output_checks.py` — deterministic, state-grounded checks on the AI's response text. **BLOCK** severity (response is rewritten to a safe fallback, same message id, so the false claim never sits in conversation history) for: an implied refund confirmation when no refund tool exists; a checkout link with no `checkout_session` in state; a claimed support ticket (or ticket number) when `ticket_receipt` is `None`; a verbatim system-prompt leak. **FLAG** severity (recorded on `AgentState.guardrail_flags`, not rewritten — too heuristic to safely auto-correct) for speculative billing explanations on `billing_question`, and for `ungrounded_invoice_claim`: a billing answer that talks about invoices without a knowledge-base search this turn and without admitting it cannot see them (no tool reads invoices, so any invoice fact is invented). It is a flag first on purpose; see `backend/evaluation/README.md` for how often it fires and what it misses.
- `unbacked_order_lookup` (BLOCK): outside `order_status`, and when no order was read this turn, a reply that asks for an order number, claims to have checked an order or says there is none on the account is replaced by the safe fallback. Found by the evaluation (order-010 to order-012); a prompt rule only half worked on the 7B model. Offline, it would have fired on 5 of 98 pre-guard replies, all asking for a number nothing can look up.
- `input_checks.py` — matches known prompt-injection shapes (instruction override, system-prompt extraction, code execution, DB manipulation, roleplay jailbreak) against the incoming message. `input_guardrail_node` uses the match to short-circuit the graph straight to `END` with a fixed refusal — `intent_router` (and its LLM call) never runs, so the payload never reaches the model at all. Detection stays intentionally narrow (the curated shapes above, not generic suspicious wording) precisely because a regex match is weaker evidence than a tool result, and an over-broad filter would refuse legitimate messages.
- **Input safety is a cascade, not a single check.** Anything the regex layer doesn't match still goes to `intent_router`, which now scores `safety_confidence` in the *same* structured-output call that classifies intent (free — no extra LLM round trip). Below `_SAFETY_CONFIDENCE_THRESHOLD` (0.7, in `app/agent/routing.py`), routing detours to `safety_judge_node`: a dedicated second LLM call, with a prompt focused only on that one decision, before anything else (retrieval, customer context, response writing) runs. Most conversations never reach it — that's the point of the cascade, paying for a closer look only when the cheap signal is genuinely unsure.

**Empirically, the middle tier under-triggers with `qwen2.5:7b-instruct`.** Live-tested a request (asked in Spanish) for step-by-step instructions to hack into someone else's database — a real misuse attempt that dodges every regex pattern (no SQL syntax, no classic jailbreak phrasing) — and `intent_router` still scored it `safety_confidence: 0.9`, above the 0.7 threshold, so `safety_judge_node` never ran. The request only got refused because `response_writer` declined it on its own (the same unenforced, model-dependent guarantee Stage 6 already flagged). The cascade's wiring is correct (unit-tested with mocked confidence values across both branches), but the threshold is an untuned guess — calibrating it needs labeled adversarial cases, which is exactly what Stage 9's evaluation dataset should provide, not something to hand-tune here without data.

**Calibrated after Stage 9.** With labeled adversarial cases in the dev set, the threshold sweep showed the problem was not the threshold: both LLM tiers scored every regex-evading attempt as safe, because their definition of unsafe was too narrow (and leaned hard towards "safe"). `intent_router` and `safety_judge` now share one `MISUSE_DEFINITION` (`app/agent/prompts/safety_policy.py`), and the threshold moved from 0.7 to 0.95 based on the sweep. Result on the dev set: 3 of 6 such attempts refused end to end (was 0 of 6), no legitimate message refused. Numbers and caveats live in `backend/evaluation/README.md`.

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

See `.env.example` for the full list. Key ones: `LLM_PROVIDER` (`anthropic` | `google` | `ollama`), `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OLLAMA_MODEL`/`OLLAMA_BASE_URL` (no key needed — requires `ollama pull qwen2.5:7b-instruct` + `ollama serve` running locally), `EMBEDDING_PROVIDER` (`google` | `ollama`), `OLLAMA_EMBEDDING_MODEL` (requires `ollama pull nomic-embed-text`), `DATABASE_URL`, `LANGFUSE_TRACING_ENABLED`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` for the self-hosted Langfuse stack in `docker-compose.yml`.

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
- [x] Stage 10 — Chat widget (**Mew**). **10a backend (done, see below)** and **10b the widget (done, see below)**
- [x] Stage 11 — README, diagrams, demo scenarios (`docs/demo.md`), known limitations. The visual design pass of the widget and the README is left for later (the owner will define it); the open backlog is below

### Stage 12 status (the back office, in progress)

Built: the tenant configuration cache, the admin API (`/api/admin`: roles and permissions per action, placeholder login, tenant list, tenant configuration; mounted only with `ADMIN_API_ENABLED=true` in a local environment) and the `backoffice/` shell (login pending page with a role picker, tenant combo, configuration page). Also built: a viewer of conversations and messages with the identification timeline, and the human handoff (ADR-0017): an escalation leaves the conversation waiting for a person, who joins from the back office's Escalations tab under the name they entered at login, chats one to one with the visitor (the widget polls every few seconds and shows their messages and "joined/left" notices) and closes it, which gives it back to the assistant and resolves the ticket. Next: secrets and integrations (rotate signing secrets, the orders endpoint, SMTP; encrypted write-only credentials), and a Zendesk destination for escalations.

### Orders demo (rejecting and returning an order)

The example shop page has a login button per demo customer (`mail1` to `mail4`, one order each: open $29.99, open $69.99, in delivery $69.99, in delivery $29.99). A logged-in customer can ask about their orders and reject or return one (ADR-0018): an open order is cancelled after a confirmation, an order in delivery cannot be rejected (it is returned once it arrives), and a $69.99 order is first offered to be kept for $14.00 back (20%) or $21.00 in credits (30%). Rules in `app/business/returns.py`; nothing moves money, it is recorded in `order_adjustments`. `python -m app.db.seed --reset-demo` puts the demo orders back. Not built: the return after delivery, a real refund or credits API.

Buttons are not text: a click is sent as `input: {type: "action", action, order_id?}` and decided by rules, with no model (no `intent_router`, no reading). The server checks that the latest assistant reply really offered that action (`app/chat/actions.py`), takes the text the click shows in the conversation from the card, and `order_return` applies it only if it fits the step the customer is in; a click that was not offered or does not fit is answered with "I didn't understand", never an error. A malformed input is a 422, and the widget then offers to start a new conversation. Written text is `input: {type: "text", message}` and still goes through the model; the old `{message}` body is accepted for now.

Every turn that goes through `order_return` writes one row to `return_events` (same transaction as the reply): the step before and after, button or text, the decision, the outcome, what was offered and taken, timing. It holds no free text, so it can outlive the messages' retention; a funnel is those rows grouped by conversation and order, and abandoning is a last row that is not final. The same facts are tagged on the Langfuse trace (`input_type`, `action`, `return_outcome`).

### Stage 10b status (the widget)

Done (PRs #89 to #95 and the Docker/docs PR): `frontend/` builds one script, `mew.js?key=...`, that renders into an `about:blank` iframe (ADR-0015). The `Mew('open' | 'close' | 'show' | 'hide' | 'config', ...)` queue, the server-held conversation streamed over `fetch` (SSE), a 24 hour conversation window shared across tabs, the shop's `getToken` login callback, the one-time-code identity form with `/api/chat/resume`, the unread badge, the sound, a safe markdown renderer (no HTML path), and image attachments as a **preview only** (nothing is uploaded). `docker compose up --build` serves an example shop page on `http://localhost:8080`, the origin the dev tenant allows. Verified in a real Chrome against the local backend; the sound was not heard, only that it is triggered.

Known limits: an expired session retried mid-conversation opens a new conversation and leaves the old messages on screen; a reload offers both identification methods because the stored identity request does not record which it offered; the unread badge does not survive a reload; no italics, tables or code blocks in markdown.

### Stage 10a status (backend for the widget)

Done (PRs #62 to #87; the last two, anonymous evaluation cases and allowed origins per tenant, may still be open when you read this): tenants with a public key and rotating secrets; the shop's signed token exchanged for a session (`POST /api/auth/login`); anonymous conversations (`POST /api/conversations`); the server holding each conversation's messages with idempotent retries and one turn at a time; `GET /api/conversations/{id}/messages`; one-time codes (`/api/auth/otp/request` and `/verify`); scopes per identity level and a per-intent permission table, with `request_identity` asking a visitor to identify when a scope is missing and `POST /api/chat/resume` answering the pending message afterwards; rate limits; allowed origins per tenant; a `small_talk` intent so a thank-you does not open a ticket; anonymous cases in the evaluation suite. The reasoning is in ADR-0013 and ADR-0014.

Identifying with an email and an order id is built end to end (PRs #102 to #106 and the widget form): the orders come from an async `OrderSource` interface with a simulated `orders` table behind it until the shop's API is wired, the session names that one order and never the customer, and the agent's `order_status` intent reads it. Identification attempts are recorded in `identification_events` (masked and hashed email, no code, no token, no full order id; see ADR-0014). Not built yet: a real email provider; the retention job (archive old messages, purge anonymous conversations).

### Before production

Known and deliberately left for later; none of it matters for the portfolio demo, all of it matters for a real deployment.

- **Retention job.** Archive messages of conversations inactive for more than 7 days to another table, purge anonymous conversations sooner (about 5k conversations a day x 10 messages), and purge `identification_events` after 90 days. Until it exists the audit table and the messages only grow.
- **Real email provider for one-time codes.** Each tenant can have its own SMTP server (`tenant_smtp`, password encrypted with `SECRETS_ENCRYPTION_KEY`) and `SmtpOtpSender` uses it; there is no way to set it yet except in the database (the back office page is next). A tenant without one cannot send codes outside local environments, and the dev sender prints the code to the log. Not tried against a real mail server, only against a fake one. Sending is synchronous, so a customer's email takes longer to answer than an unknown one (a timing difference that reveals which emails exist); send after the response before going live. A failed delivery is still audited as `code_sent`.
- **A real back office login.** The back office starts with a placeholder login (an "Enter" button and a role picker) and its API is mounted only in local environments; passwords, one-time codes or SSO still have to be chosen and built, and until then it must not be reachable in a deployment (ADR-0016).
- **Real secrets.** `SESSION_SIGNING_KEY` and `AUDIT_HMAC_KEY`, each at least 32 characters and different from each other, and `SECRETS_ENCRYPTION_KEY`, a Fernet key (the API refuses to start otherwise outside local environments; losing the encryption key means entering the stored credentials again); the dev tenant's public key and secret must not exist in a real database (the seed already skips them).
- **Tenant signing secrets at rest.** HS256 needs the raw key, so `tenant_secrets` are still stored in the clear; encrypt them with the same mechanism as the SMTP password (`app.core.secrets`).
- **Rate limits and origins** are estimates without traffic behind them; set `TRUSTED_PROXY_COUNT` for the real proxy chain.

### Open backlog

- Product-fact guardrail: `ungrounded_invoice_claim` flags invented invoice claims (FLAG only, it does not change the reply) and `unbacked_order_lookup` blocks order requests nothing can back. Open: decide whether to promote the invoice flag to BLOCK, and a check for the same kind of invention outside billing and for an admission followed by an invented detail. Written by the AI at the owner's request.
- Retention job: archive old messages, purge anonymous conversations, and purge `identification_events` after 90 days.
- Simulated `orders` table and `order_lookup` as an identity method; a real email provider; the retention job.
- Widget polish: store the identity methods with the identity request, keep old messages off screen after a 401 retry, upload for image attachments, visual design.

Update this checklist as stages complete.
