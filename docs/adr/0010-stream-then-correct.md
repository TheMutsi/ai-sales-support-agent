# ADR-0010: Stream tokens live, and correct afterwards if a guardrail rewrites the answer

- **Status:** Accepted
- **Introduced in:** PR #28 (Stage 8); typed `done` summary in PR #30, `error` event in PR #40

## Context

Output guardrails (ADR-0008) run after `response_writer` has finished. Streaming
tokens as they are generated feels instant, but the streamed text may be the very
answer a guardrail then blocks. Buffering the whole answer until checks pass is safe
but makes every response feel slow, to protect against a case that is rare.

## Decision

`/api/chat` speaks Server-Sent Events with a small, fixed vocabulary:

| Event | When |
|---|---|
| `delta` | Each token chunk from `response_writer`, live |
| `message` | The whole answer at once, when nothing streamed (input refused by tier 1 or 3) |
| `correction` | The final text, when it differs from what was streamed (a guardrail rewrote it) |
| `done` | Always last on success: a typed `ChatTurnSummary` (intent, escalation, ticket, flags, eligibility) |
| `error` | The graph failed; replaces `done`, so a client can tell a failure from a dropped connection |

Only `response_writer`'s tokens are streamed; nodes such as `intent_router` also call
the model, but their structured output is not user-facing.

`ChatTurnSummary` is read from graph state, not parsed from text, and the evaluation
suite consumes the same contract (ADR-0012).

## Consequences

- The common path streams immediately.
- On the rare blocked answer, the user briefly sees the false text before the
  correction replaces it. The client must apply `correction` (the frontend has to
  handle it), and nothing false stays in the conversation history the client resends,
  as long as it stores the corrected text.
- Clients and the evaluation runner get structural outcomes without guessing from
  prose.
- Error details go to the server log, not the wire.

## Alternatives

- **Buffer until guardrails pass.** No false text is ever shown; every answer arrives
  in one block after the full generation time.
- **Run checks incrementally on partial text.** Claims are often only recognizable
  at the end of a sentence; complex for little gain.
- **WebSockets.** Bidirectional transport the chat does not need; SSE works over plain
  HTTP and is trivial to consume.

## References

- `backend/app/api/chat.py` (`stream_chat_turn`)
- `backend/app/schemas/chat.py` (`ChatTurnSummary`)
