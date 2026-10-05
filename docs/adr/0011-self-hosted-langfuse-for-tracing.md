# ADR-0011: Self-hosted Langfuse for tracing, instead of LangSmith

- **Status:** Accepted. Supersedes the LangSmith choice in the original plan.
- **Introduced in:** PRs #24 and #26 (Stage 8)

## Context

The original plan traced with LangSmith: LangChain integrates with it through two
environment variables. In Stage 8 two requirements made that a poor fit. The project
should run end to end locally and for free (it already supports Ollama for the same
reason, ADR-0004), and self-hosting LangSmith is an Enterprise-only, paid add-on.

## Decision

Trace with **Langfuse, self-hosted** from `docker-compose.yml` (the `langfuse-*`
services: web, worker, Postgres, ClickHouse, Redis, MinIO).

- **Off by default** (`LANGFUSE_TRACING_ENABLED=false`). When off, no Langfuse client
  or callback is constructed; a test enforces that.
- **One owned span per chat turn** (`chat_turn`), tagged upfront with `customer_id`,
  `conversation_id`, `environment`, `model` and `app_version`. `conversation_id` maps
  to a Langfuse session, so the turns of one conversation group together.
- **`intent` is patched onto the span mid-run**, the moment `intent_router` finishes,
  because it is unknown when the span opens.
- A LangChain `CallbackHandler` nests every graph node, LLM call and tool call under
  that span.
- `configure_langfuse()` copies keys from the typed `Settings` into `os.environ` once
  at startup, because the Langfuse SDK reads only the process environment.
- The `.env.example` keys are local bootstrap values the compose stack seeds itself
  with, so tracing works with no sign-up. They are not secrets and must not be reused
  for any shared deployment.
- The evaluation suite can run as a Langfuse dataset experiment (`--backend
  langfuse`), whose items link to the same sessions as the agent's own traces
  (ADR-0012).

## Consequences

- Full traces with no account, no cost, and no data leaving the machine.
- Six more containers in the compose file; the tracing stack is heavier than the app.
- Tracing is wired per call in the chat endpoint rather than by a global switch, so a
  new entry point into the graph must attach the handler itself.
- Some documents and the original plan still say LangSmith; `CLAUDE.md` and the
  README were updated together with this record.

## Alternatives

- **LangSmith cloud.** Zero setup, but needs an account and sends traces to a third
  party; self-hosting is not available on the free tier.
- **OpenTelemetry to a generic backend.** Standard, but LLM-specific views (token
  usage, prompt and completion, tool calls, scores) would have to be built by hand.
- **Logs only.** Not enough to debug a multi-node graph.

## References

- `backend/app/core/observability.py`, `backend/app/core/config.py`
- `backend/app/api/chat.py` (`stream_chat_turn`, `_build_trace_metadata`)
- `docker-compose.yml`, `.env.example`
