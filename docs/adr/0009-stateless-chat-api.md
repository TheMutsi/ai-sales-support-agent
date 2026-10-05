# ADR-0009: The chat API is stateless; the client resends the conversation

- **Status:** Accepted
- **Introduced in:** PR #24 (Stage 8)

## Context

A multi-turn conversation needs history somewhere. LangGraph offers checkpointers
keyed by a thread id, which would let the client send only the latest message.
But most of `AgentState` is per-turn data with overwrite semantics
(`customer_context`, `checkout_session`, `ticket_receipt`, `eligibility_result`),
owned by whichever node ran in that turn (ADR-0001).

## Decision

`POST /api/chat` takes the full `messages` list on every request, the same shape as
the Anthropic and OpenAI chat APIs, and every request is an independent graph run
starting from an empty state. The graph is not checkpointed.

- `customer_id` is required: every tool the graph reaches takes a real customer, and
  `tickets.customer_id` is a non-nullable foreign key. There is no anonymous path.
- The last message must come from the user; anything else is rejected at validation.
- `conversation_id` is optional and only groups turns in traces (Langfuse session).

## Consequences

- No stale tool output leaks across turns. With a checkpointer, a refund ticket from
  turn 1 would still be in `response_writer`'s context when turn 3 asks about
  pricing, and the output checks would treat it as created in this turn.
- Any server instance can serve any request; there is no session store to run.
- The client owns history, so it can send a fabricated assistant message. The agent
  treats history as conversation, not as facts: every fact it states must come from
  a tool in the current turn, and the output checks verify against current-turn
  state only.
- Request size grows with the conversation. Fine for support chats; a long-running
  conversation would need truncation or summarization.
- Facts are re-fetched every turn (customer context, for example). That is a few
  cheap queries, and it means they are never stale.

## Alternatives

- **LangGraph checkpointer.** Would need every per-turn field reset at the start of
  each run, or reducers that know about turns: more state machinery to get the same
  isolation the stateless design gives by construction.
- **Server-side history in Postgres.** Same isolation question, plus a table and
  retention policy, for a demo without user accounts.

## References

- `backend/app/schemas/chat.py` (`ChatRequest` and its docstring)
- `backend/app/api/chat.py` (`_build_initial_state`)
