# ADR-0020: Every turn of a return is recorded in its own table, apart from the messages

- **Status:** Accepted
- **Introduced in:** the `return-events` PR

## Context

To judge the return flow (ADR-0018 and ADR-0019) someone has to answer: of the customers who ask
to cancel, how many accept the first offer, how many the one with the gift, how many cancel;
which of refund and credits wins, by order value; how often a written message was misread; how
much is given away. What existed could not answer it. The conversation keeps the text of what was
said, the final result is in the order and in `order_adjustments`, but the path (the step the
customer was in, what they did, what the step answered) was not stored, and rebuilding it from
the text of messages is fragile: the text changes with the copy and the amounts.

The obvious place, columns on `messages`, has a worse problem. A retention job that archives
messages and purges anonymous conversations is planned (see "Before production"), and analysis
cannot live in the table that is meant to be emptied.

## Decision

- A table `return_events`, one row per turn that went through `order_return`, written with the
  reply in the same transaction (`finish_turn`), so a row and the reply it describes cannot
  disagree. A turn that did not reach that step writes nothing.
- It holds: who (tenant, conversation, customer, identity level), which message (`user_seq`),
  how it was read (`input_type` text or action, the `action`, the order a click named, and the
  decision taken: reject, refund, credits, keep or unclear), where they were (`stage_before`,
  `stage_after`, null when it finished), the `outcome` of the turn, the order (id, status,
  amount), how many orders were shown to choose from, what was offered and what was taken (refund,
  credit, gift), and the model, app version and the duration of the turn in milliseconds.
- **No free text.** What they wrote is in `messages` (found by `user_seq` while that message
  exists), so the table has nothing to purge for privacy and can outlive the messages. The foreign
  keys to tenant, conversation and customer are `ON DELETE SET NULL`, like
  `identification_events`.
- The record is built from the state the graph ended with (`app/chat/return_events.py`), only from
  what a step did, never from what a model said.
- The same facts are tagged on the Langfuse trace (`input_type`, `action`, `return_outcome`), to
  filter a single turn; Langfuse is for looking at one case, the table is for aggregates.

## Consequences

- The funnel is a `GROUP BY` over rows ordered in time by (conversation, order): the share that
  goes `check` to `offer` to `final_offer` to a final outcome, and conversion by `offer_*` and
  `order_amount_cents`.
- Abandoning has no row of its own (nobody does anything when they leave). It is a last row for a
  (conversation, order) whose outcome is not final; the pending return lapses after 15 minutes.
- A click that was not offered (a stale button) writes nothing, because no turn runs for it.
  Measuring how often it happens would need its own record.
- Only what happens from now on is recorded; there is nothing for earlier conversations.
- The duration separates the two paths: a click takes tens of milliseconds, a written turn the
  classifier's seconds. On the first real run, 6.4 s against 12 to 39 ms.
- The table has no retention policy of its own yet; it holds no free text, so it is not part of
  the retention job's privacy purge, but it will need a decision on how long to keep it.

## Alternatives

- **Columns on `messages`** (`action` on the visitor's, `outcome` on the reply's). Rejected: it
  disappears with the retention job, records only the result of a turn and not the step before it,
  and mixes analysis into the table the widget reads.
- **Only Langfuse metadata.** Rejected as the only source: it is built for inspecting one trace,
  not for SQL aggregates, and has its own retention. It is kept as a complement.
- **Store the text of the message in the row.** Not done: it would tie the table to the messages'
  privacy and retention, which is the reason for having it apart. It is one column if wanted later.
- **An `attempt_id` per return.** Not needed yet: an order cannot be offered again once kept or
  cancelled, so (conversation, order, time) groups an attempt.

## References

`backend/app/db/models.py` (`ReturnEvent`), `backend/alembic/versions/7dee0b60164c_add_return_events.py`,
`backend/app/chat/return_events.py`, `backend/app/chat/turns.py` (`finish_turn`),
`backend/app/api/chat.py`, `identification_events` (ADR-0014), ADR-0018, ADR-0019.
