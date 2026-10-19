# ADR-0017: An escalation hands the same conversation to a person, who chats one to one

- **Status:** Accepted (built across the handoff PRs; verified end to end in a real browser with the real agent)
- **Introduced in:** Stage 12 (the back office)

## Context

Today an escalation creates a `Ticket` and the assistant says so; nothing connects the ticket to
the conversation, and nobody can answer. The owner wants the back office to answer: when the
assistant escalates, a person joins the visitor's chat and they talk one to one ("Mónica joined the
chat"), with polling being enough. Zendesk may later be another destination.

## Decision

- **Three speakers in one conversation:** the visitor (`user`), the assistant (`assistant`) and a
  person from the back office (`human`, shown under their display name). Notices such as "an agent
  joined" are `system` messages (kind `system`), which are not anyone's speech.
- **The conversation has a handoff state**, not a new table: `none` (the assistant answers),
  `waiting` (a ticket was opened and no agent has joined), `active` (an agent is in), plus the
  agent's display name, when it was requested and the ticket that started it.
- **An escalation sets `waiting` when its reply is saved**, in the same transaction, with the
  ticket's id taken from the turn's receipt, so the API layer decides it from what the agent did and
  the agent code does not change.
- **While `waiting` or `active` the assistant does not answer.** The visitor's message is stored
  (idempotently, by its client id) and the `done` event says `handoff`. No model call is made.
- **What a person or a notice said is not the assistant's history**: it is left out of the
  messages the model continues from, so a returning assistant does not imitate or contradict them.
- **Polling, not a socket.** The widget reads `GET /conversations/{id}/messages` (which now also
  says the handoff state) every few seconds while a person has the conversation; the back office
  polls its own queue. Simple, works behind any proxy; the cost is a few seconds of delay.
- **Destinations are an interface.** The back office is the first destination; Zendesk would be
  another behind the same interface (not built).

## Consequences

- An escalated visitor who writes again no longer gets the assistant. If nobody joins, they wait;
  a timeout or an out-of-hours message is a later decision.
- System notices are stored in English; localizing them is a follow-up.
- Only a visitor who can open a ticket (an identified customer) can reach a person; an anonymous
  visitor cannot escalate today.
- The assistant does not see what the person said when it takes the conversation back.

## Not built yet

A destination other than the back office (Zendesk) behind the interface; a timeout or out-of-hours
message when nobody joins; the visitor ending the handoff themselves; localized notices;
notifying an agent (the inbox only polls, so someone has to be looking at it); ownership of a
conversation between agents (the placeholder identities cannot support it); messages the visitor
sent during a handoff have no reply, so retrying one with the same id after the handoff ends makes
the assistant answer it late, and the history it continues from then has consecutive visitor
messages.

## References

- `backend/app/chat/turns.py`, `backend/app/api/chat.py`, ADR-0013 (the server holds the
  conversation), ADR-0016 (the back office).
