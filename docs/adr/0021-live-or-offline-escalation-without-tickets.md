# ADR-0021: An escalation is live or offline, decided by rules, and kept on the conversation

- **Status:** Accepted (built and tested; not yet tried by a person in the browser)
- **Introduced in:** Stage 12 (the back office). Refines ADR-0017.

## Context

Every escalation created a `Ticket` (with a subject and description the model wrote) and left the
conversation waiting for a person to join. Two problems: a person is not always there (at night, on
a weekend, nobody logged in), so a visitor waited for no one; and some requests do not need a person
this minute (a customer insisting on returning an order that is already on its way). Also the
ticket's summary duplicated a conversation that is short and could say something the customer never
did.

## Decision

- **No ticket table.** The conversation is the record; old tickets are kept as `tickets_archive`,
  with no model and no foreign key to customers, out of the code's way. It gets `escalation_reference` (a follow-up
  number such as `MF-7K3Q9X2A`, unique), `route`, `reason`, `category`, `status` (`open` or
  `resolved`), when it was escalated and resolved, who resolved it and a note. Whoever takes it reads
  the conversation. This also removes one model call per escalation.
- **Two routes, decided by `app.business.escalation.decide_route`**, a pure function of facts the
  node collects. In order: an order already in delivery is `offline` (not urgent); outside the
  tenant's support hours is `offline`; no agent available is `offline`; otherwise `live`.
  Its facts carry a timezone-aware `now` (a naive one is refused), and a stored schedule with an
  unknown time zone fails when the tenant's configuration is read, not on a customer's turn.
- **`live`** is the handoff of ADR-0017 (the visitor waits in the chat). **`offline`** gives the
  visitor the number and leaves the assistant answering: nobody is coming to the chat. A person
  later marks it resolved from the back office.
- **"Available" means seen recently.** The back office inbox polls every few seconds; each poll by a
  role that can answer records a sighting in `agent_presence`, and one not seen for 45 seconds stops
  counting. There is no "online" switch to forget.
- **The schedule is per tenant** (`tenants.support_hours`: time zone, opening and closing time,
  weekdays); empty means always open. A closing time earlier than the opening one is a night shift
  that ends the next morning, counted on the weekday it started. A malformed one (including one that
  opens and closes at once) is logged and taken as always open.
- **One open escalation per conversation.** A customer who insists is shown the same number again
  (`TurnStart.open_escalation`). An open offline one becomes live, with the same number, once someone
  can join; a live one stays as it is. A resolved one is replaced by the new request and moves to
  `escalation_history`, so its number can still be searched and its note is not lost.
- **A reply may quote only the conversation's own number**, the one opened this turn or still open;
  any other `MF-` number is blocked as invented (`fabricated_ticket_claim`).
- **The order goes along only when it is certain.** When a customer pushes back after a "no" in the
  return flow, an order on its way decides "not urgent" only if the customer has nothing they could
  still cancel; any doubt leaves it out, so the customer gets a person rather than a wrong wait.
- **The inbox is a search** over escalated conversations: status, kind, category, tags (all of them),
  the visitor's public properties (`key:value`), dates, and text (number, customer, messages).

## Consequences

- The migration backfills conversations that had a ticket (its id becomes the number, the reason
  `agent_available`) and renames `tickets` to `tickets_archive`, recording each ticket's
  conversation, so nothing is lost; `downgrade` renames it back and links the conversations again.
  `alembic/env.py` keeps autogenerate from proposing to drop the archive.
- The model no longer writes anything for an escalation, so the writer can only repeat the number
  and what happens next that the context states.
- The public `ticket_created` field of a turn and the evaluation's `expected_ticket_created` keep
  their names so earlier evaluation runs stay comparable; they now mean "an escalation was opened".
- Not built: editing the support hours from the back office (set in the database), a way for the
  visitor to find their number again, and notifying the customer when an offline escalation is
  resolved.
