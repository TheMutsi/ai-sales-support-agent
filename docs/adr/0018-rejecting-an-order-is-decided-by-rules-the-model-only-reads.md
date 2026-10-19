# ADR-0018: Rejecting an order is decided by rules; the model only reads what the customer means

- **Status:** Accepted
- **Introduced in:** the orders demo (PRs #130 to the flow PR after #132)

## Context

A customer logged in by the shop can ask to reject or return an order. The product rules are
specific and money-adjacent: an order not shipped yet can be rejected (cancelled); one on its
way cannot, it is returned once it arrives; and before an order worth at least $50.00 is
rejected the customer is offered to keep it for 20% back on their card or 30% as credit. Taking
the offer means the order is kept, not returned. Until now every request like this ended at a
person (`refund_request`), and the guardrail said no tool could ever confirm a refund.

It takes several turns (request, offer, answer), so something has to remember where the
customer is, and a 7B model must not be the one deciding what is allowed, what the numbers
are, or whether something happened.

## Decision

- A new intent, `order_return`, behind the `refund:request` scope (verified customers only).
  Cancelling a subscription stays `refund_request`; rejecting one order is `order_return`.
- `app/business/returns.py` holds the rules in integer cents (what can be done, the offer,
  rounding half up, the $50 threshold, amounts in integer cents). The model never computes an amount.
- The `order_return` node asks the model for one thing, a `ReturnReading`: which of the
  customer's orders they mean (validated against their own list) and which of reject / refund /
  credits / keep / unclear they said. Everything after that is code: the node starts the offer or
  the confirmation, applies the choice through `OrderSource.cancel_order` or
  `keep_order_with_retention`, or asks again.
- Where the customer is lives on the conversation (`pending_return_order_id`, `pending_return_stage`),
  written when the reply is stored, and dropped if not answered within 15 minutes. While one is
  pending, a bare answer the classifier files as `small_talk` ("yes") continues it; any other
  request (a subscription cancellation, a person, an order status, a question) goes its own way
  and the pending return waits until it lapses.
- The source enforces the invariants under a row lock: an order is cancelled only while open and
  only if it was not kept with the offer; the offer is recorded at most once per order and its
  amounts are computed from the order, not taken from the caller.
- Everything this step says is fixed text it writes itself from the result (`reply_for`), and the
  graph ends there: no model words a question or reports what happened, so a reply cannot invent
  an amount, an order number or a cancellation. The offers are **cards** (see `app/cards.py`), the
  text never names cancelling (the "No thanks" card is the button for that) and never shows an id.
- Two chances: the first offer is the two options (a refund to the card, or credit); declining it
  shows the **last offer**, the same three plus a free gift (a product card, a "+" and the choices);
  declining that cancels an open order (or, for one in delivery, says to return it once it arrives).
  Output guardrails: a refund claim is allowed only when the return step recorded one, and
  `unbacked_order_action_claim` blocks "your order has been cancelled" or "credits have been added"
  in the replies of other steps.
- Nothing moves money: the refund and the credits are recorded in `order_adjustments` and
  stated to the customer, which is all the simulation does.

## Consequences

- The model can misread a message, but a misreading cannot cancel an order on the first request
  (there is always an offer or a confirmation turn first), cannot pick an order that is not the
  customer's, and cannot invent an amount. A misread answer *during* the 15 minutes after an
  offer can still cancel an open order: declining the offer and confirming a cancellation are
  each one turn.
- Cancelling an open $29.99 order takes two turns (ask, confirm); an open $69.99 order takes the
  offer first. Declining the offer for an order in delivery changes nothing: the return after
  delivery is only explained, there is no return action yet.
- The existing `refund_request` path (ticket for a person) is untouched; "cancel my order" moved
  from it to this flow (evaluation case `order-012` changed accordingly).
- Not built: the return after delivery, telling "already kept"
  from "not allowed" to the customer, a real refund or credits API.

## Updates

- **Which order first.** Asking to cancel never opens with an offer: the order is shown and the
  customer is asked "is this the one?" (stage `check`, outcome `confirm_order`), with "Yes, this
  one" and "No, keep my order". Naming another order in words moves to that one. With several open
  orders the cards are the list to choose from, and choosing one counts as the confirmation. Only
  then the offer (or the confirmation of a cheaper order) follows. A request that finds nothing to
  cancel now answers with its fixed text (before, it added no reply and the visitor's own message
  was sent back as the answer).
- **Buttons are not read by the model.** The cards send a typed action decided by rules, and only
  written words go through the reading above, so the misreading described in the consequences can
  now only happen with typed text (ADR-0019). Each turn is recorded in `return_events` (ADR-0020).
- The free gift of the last offer is the Shapermint Essentials Everyday Wireless Jelly Bra
  (`GIFT_NAME`).

## Alternatives

- **Let the model call refund/cancel tools directly.** Rejected: it would decide eligibility and
  amounts, and the repo's rule is that a function computes what a function can.
- **Infer the pending offer from the stored messages.** Rejected: fragile and not checkable;
  an explicit stage on the conversation is.
- **Always escalate to a person.** The previous behaviour; it cannot honour the product rule.

## References

`backend/app/business/returns.py`, `backend/app/agent/nodes/order_return.py`,
`backend/app/orders/simulated.py`, `backend/app/chat/turns.py`, ADR-0002, ADR-0008, ADR-0014.
