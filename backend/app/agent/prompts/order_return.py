"""The one decision `order_return` leaves to the model: what the customer's message means.
What happens next (the offer, the numbers, the cancellation) is decided by rules."""

ORDER_RETURN_READING_PROMPT = """You read what a customer means about an order they want to reject or return.

Orders the customer can reject or return (use an order_id exactly as written here):
{orders}

{situation}

Answer with:
- order_id: the order the customer means, copied from the list, or null if they did not say and
  you cannot tell.
- choice, exactly one of:
  - reject: they want to reject, cancel or return the order, or they confirm that they do
    ("yes, cancel it", "no thanks, I just want to cancel", "return it").
  - refund: they take the offer of part of the price back on their card.
  - credits: they take the offer of credit.
  - keep: they changed their mind and want to keep the order as it is, without the offer
    ("never mind", "forget it", "leave it").
  - unclear: none of the above, or you cannot tell.

Read the latest message only, with the conversation for context. Do not answer the customer."""

NO_PENDING_SITUATION = "The customer has just asked to reject or return an order."

OFFER_SITUATION = (
    "The customer was offered to keep order {order_id} and get either part of the price back "
    "on their card (refund) or as credit to spend in the shop (credits), or to reject it anyway. Their latest message "
    "answers that offer."
)

FINAL_OFFER_SITUATION = (
    "The customer declined the offer for order {order_id} once and was offered it again, this "
    "time with a free gift on top of either. Their latest message answers that."
)

CONFIRM_SITUATION = (
    "The customer was asked to confirm that they want to cancel order {order_id}. Their latest "
    "message answers that question."
)
