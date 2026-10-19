# ADR-0019: A button is a typed action decided by rules; only written text goes to the model

- **Status:** Accepted
- **Introduced in:** the PR chain from `action-input` to `return-events`

## Context

The cards of a reply (ADR-0018: offers, "yes / no" questions, a list of orders to pick from)
were buttons that sent their own text as if the visitor had typed it. The idea was that a click
and a sentence behave the same, but it meant that a click, which has no ambiguity, went through
two model calls: the intent classifier and the return reader. The reader misread plain answers:
a bare "no thank you" repeated the offer instead of moving to the last one (the reading was most
likely `unclear`; no trace was kept), and, probing the reading prompt with the local model, "no
gracias" came back as taking the refund, which would record money nobody asked for. A
button that is decided by a model is a bug waiting in the part of the flow that handles
refunds.

Every messaging platform separates the two: a Telegram `callback_query` is not a `message`, a
Slack `block_actions` is not a message event, a Messenger button carries a payload apart from
its text, and Rasa lets a button payload skip the NLU (confidence 1.0) while keeping free text
as the fallback.

## Decision

- The request carries `input`, a union on `type`: `{"type": "text", "message"}` (a model reads
  it) or `{"type": "action", "action", "order_id"?}` (rules decide it). The old `{"message"}` body
  is still accepted as text, for widgets already loaded in a shop's page; it is meant to go away.
- `action` is a closed enum (`CardAction`): `confirm_order`, `choose_order` (with `order_id`),
  `keep_order`, `confirm_cancel`, `take_refund`, `take_credits`, `decline_offer`. The server puts
  it on the cards it builds, the widget sends it back unchanged.
- **Two checks, with different jobs.**
  1. *Was it offered?* (`app/chat/actions.py`) The latest assistant reply's stored cards must hold
     that action (and that `order_id`). This covers a button from an older question in another
     tab, a repeated click and an action made up by hand, and it is read from what was really
     shown, not from a list in the code.
  2. *Does it fit the step?* `order_return` has a table of the actions valid in each stage of the
     return (`_ACTIONS_BY_STAGE`, and one for "nothing pending"). One that does not fit changes
     nothing and asks the same question again.
- The text a click shows in the conversation (and stores, so another tab loads it) is the card's
  `message`, taken from the stored card. The client never supplies it.
- **No model for a click.** The graph starts at `route_start`: a click from a verified customer
  (a customer id and the `refund:request` scope) goes straight to `order_return`, skipping the
  input filter, the classifier and the safety cascade, because there is no free text to read. The
  step maps the action to a reading by rules and uses the same code path as written text after
  that. A click without that scope is not trusted and takes the ordinary path as text.
- **Errors.** A malformed input (an action outside the enum, a missing field, an unknown `type`)
  is a 422: the widget cannot produce it, so it means a bug or tampering. The widget stops the
  conversation with "There was a problem with this conversation" and a button to start a new one,
  and says nothing that would help probing. A well-formed click that was *not offered* or does not
  fit the step is not an error: it is a normal thing for a visitor with two tabs to do, so the
  answer is a fixed "Sorry, I didn't understand that. Could you ask it another way?" with the
  cards of the open question (nothing is stored or run for it).
- A retry of a click that was already stored replays its reply (the idempotency of ADR-0013 comes
  first, so the check of what was offered is skipped for it).

## Consequences

- A click costs 12 to 40 ms and no tokens; a written turn through the classifier took 6.4 s on the
  local 7B model in the same conversation.
- A misreading by the model can no longer touch a refund or a cancellation through a button. It
  still can through typed words ("no gracias" read as a refund was fixed in the reading prompt and
  checked on 10 phrasings, not proved), so the typed path keeps the limits of ADR-0018.
- Adding a button is a member of `CardAction`, the card that carries it and a row in the table of
  the step that handles it; the type system and `test_card_actions` fail if one is forgotten.
- The 422 body lists the allowed actions (FastAPI's message). They are not secret: they are in the
  widget.
- A "not understood" reply to a stale click is not stored, so it disappears on reload. That is
  deliberate (it is not part of the conversation) and is a known limit of the current widget.
- Only `order_return` handles actions today. Another flow with buttons adds its own table, and
  `route_start` its own destination.

## Alternatives

- **Keep sending text and make the model's reading more reliable.** Rejected: it narrows the error
  without removing it, and costs two model calls for something with no ambiguity.
- **Two optional fields on the old body (`message` and `action`).** Rejected: it allows invalid
  combinations (both, neither, an action with a text that contradicts it) that a union on `type`
  makes impossible, and the next kind of input (an upload) would be another optional field.
- **Validate the action only against the stage** (no check of what was offered). Rejected: it would
  accept an old button that happens to match the current step. The two checks catch different
  things.
- **Return an HTTP error for an action that was not offered.** Rejected: a stale button is not a
  bug, and an error would show a visitor a failure for doing nothing wrong.
- **Send the card's text with the action.** Rejected: the client would then choose what appears in
  the stored history.

## References

`backend/app/schemas/chat.py` (`ChatRequest`), `backend/app/schemas/cards.py` (`CardAction`),
`backend/app/chat/actions.py`, `backend/app/agent/routing.py` (`route_start`),
`backend/app/agent/nodes/order_return.py` (`_ACTIONS_BY_STAGE`), `frontend/src/data/chat.ts`
(`pick`, `restart`), ADR-0013, ADR-0018.
