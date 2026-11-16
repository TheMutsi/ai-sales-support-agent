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

- **No ticket table.** The conversation is the record. It gets `escalation_reference` (a follow-up
  number such as `MF-7K3Q9X2A`, unique), `route`, `reason`, `category`, `status` (`open` or
  `resolved`), when it was escalated and resolved, who resolved it and a note. Whoever takes it reads
  the conversation. This also removes one model call per escalation.
- **Two routes, decided by `app.business.escalation.decide_route`**, a pure function of facts the
  node collects. In order: an order already in delivery is `offline` (not urgent); outside the
  tenant's support hours is `offline`; no agent available is `offline`; otherwise `live`.
- **`live`** is the handoff of ADR-0017 (the visitor waits in the chat). **`offline`** gives the
  visitor the number and leaves the assistant answering: nobody is coming to the chat. A person
  later marks it resolved from the back office.
- **"Available" means seen recently.** The back office inbox polls every few seconds; each poll by a
  role that can answer records a sighting in `agent_presence`, and one not seen for 45 seconds stops
  counting. There is no "online" switch to forget.
- **The schedule is per tenant** (`tenants.support_hours`: time zone, opening and closing time,
  weekdays); empty means always open. A malformed one is logged and taken as always open.
- **One open escalation per conversation.** A customer who insists is shown the same number again
  (`TurnStart.open_escalation`); a resolved one is replaced by the new request.
- **The inbox is a search** over escalated conversations: status, kind, category, tags (all of them),
  the visitor's public properties (`key:value`), dates, and text (number, customer, messages).

## Consequences

- The migration backfills conversations that had a ticket (its id becomes the number) and drops the
  table; `downgrade` recreates it empty of its descriptions.
- The model no longer writes anything for an escalation, so the writer can only repeat the number
  and what happens next that the context states.
- The public `ticket_created` field of a turn and the evaluation's `expected_ticket_created` keep
  their names so earlier evaluation runs stay comparable; they now mean "an escalation was opened".
- Not built: editing the support hours from the back office (set in the database), a way for the
  visitor to find their number again, and notifying the customer when an offline escalation is
  resolved.
