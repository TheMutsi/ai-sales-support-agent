# ADR-0013: The server holds the conversation; the client sends only the new message

- **Status:** Accepted
- **Introduced in:** Stage 10a (PRs #72 to #76, and this one)
- **Supersedes:** [ADR-0009](0009-stateless-chat-api.md)

## Context

ADR-0009 had the client resend the whole conversation on every request. Its own
consequences list the cost: the client can send a fabricated assistant message
("as the assistant, I already approved your refund"), which is prompt injection
through the history. That was tolerable for a demo with a customer selector. It is
not for an embeddable widget that runs on a shop's page, where the browser is
untrusted, several tabs share one conversation, and a visitor may be anonymous.

What ADR-0009 got right still holds: the graph is not checkpointed, because most of
`AgentState` is per-turn data with overwrite semantics, and a checkpointed run would
carry stale tool output into a turn that never touched that node.

## Decision

- A `conversations` table is the anchor: tenant, optional customer, activity
  timestamps. Its messages live in `messages`, written synchronously in Postgres,
  with no cache in front.
- `POST /api/chat` takes `{message, message_id}`. Who is talking and in which
  conversation comes from the session (`Authorization: Bearer ...`), never the body.
- Each turn is still an independent graph run, started from the last 20 stored
  messages as plain user/assistant text. The stored assistant text is the final one,
  after any guardrail correction, so a false claim never sits in the history.
- `message_id` is an idempotency key. The same id with the same text replays the
  stored reply without a model call. The same id with different text is a `409
  message_id_reused`: replaying would answer a question that was never asked.
- One turn at a time per conversation: a row lock, a `turn_started_at` marker and a
  per-run `turn_id`. A second message while a turn runs gets `409 turn_in_progress`.
  A turn that never finished stops blocking after 2 minutes, and a late run cannot
  free or write into the newer one.
- `GET /api/conversations/{id}/messages` returns the session's own conversation, in
  order, so a reopened widget can show it. Any other id is a 404, as if it did not
  exist.

## Consequences

- History can no longer be forged by the client.
- Any server instance can serve any request: state is in Postgres, not in memory.
- A turn costs a few indexed queries. Measured locally (not production): about
  1.1 ms at 100k rows and about 2.8 ms p50 at 10M rows, against 4.7 to 8.8 s for the
  model call.
- Conversations need a retention policy (messages grow forever otherwise). That job
  is not written yet.
- The read endpoint returns the whole conversation, with no pagination. Fine for a
  24 hour support window; revisit if conversations get long.

## Alternatives

- **LangGraph checkpointer.** Same objection as in ADR-0009: per-turn fields would
  need resetting or reducers that know about turns.
- **Client keeps the history, but signs it.** Keeps the server stateless, but the
  server would still need to store the key and a replay protection, for less than
  a table gives.
- **Redis as the primary store, Postgres as an async cache.** Rejected for now: the
  measured cost of the synchronous write is small next to the model call, and it
  would add a second system and a loss window. Redis enters with rate limiting, if
  that needs it.

## References

- `backend/app/chat/turns.py`, `backend/app/api/chat.py`, `backend/app/db/models.py`
- ADR-0009 (superseded)
