"""Rejecting or returning an order, a few turns long.

The model only reads what the customer means (`ReturnReading`); what is allowed, what is
offered and the numbers come from `app.business.returns`, and every change goes through the
shop's `OrderSource`. The step keeps the customer's place between turns in `pending_return`
(stored on the conversation) and tells the writer exactly what was done in `return_result`, so a
reply can say only what really happened.

A customer's request can reach it only through a session that proved a customer (the scope is
checked in `routing.py`); the customer and the tenant come from that session.
"""

import uuid

from langchain_core.messages import AIMessage, SystemMessage

from app.agent.prompts.order_return import (
    CONFIRM_SITUATION,
    FINAL_OFFER_SITUATION,
    NO_PENDING_SITUATION,
    OFFER_SITUATION,
    ORDER_RETURN_READING_PROMPT,
)
from app.agent.state import AgentState
from app.business.returns import return_options
from app.core.llm import get_chat_model
from app.orders.factory import get_order_source
from app.schemas.agent import ReturnChoice, ReturnReading
from app.schemas.orders import (
    OrderDetails,
    PendingReturn,
    RetentionChoice,
    ReturnOutcome,
    ReturnResult,
    ReturnStage,
)

# What each way of taking the offer records and what it is called afterwards.
_TAKEN = {
    ReturnChoice.REFUND: (RetentionChoice.REFUND, ReturnOutcome.KEPT_WITH_REFUND),
    ReturnChoice.CREDITS: (RetentionChoice.CREDITS, ReturnOutcome.KEPT_WITH_CREDITS),
    ReturnChoice.FREE_NEXT: (RetentionChoice.NEXT_ORDER_FREE, ReturnOutcome.KEPT_WITH_FREE_ORDER),
}


def _actionable(order: OrderDetails) -> bool:
    options = return_options(order)
    return options.can_cancel or options.return_after_delivery


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _listing(orders: list[OrderDetails]) -> str:
    return "\n".join(
        f"- order_id {o.order_id}: {_dollars(o.amount_cents)}, {o.item_name or o.plan_slug + ' plan'}, placed "
        f"{o.created_at:%b %d}, status {o.status.value}"
        for o in orders
    )


async def _read(state: AgentState, orders: list[OrderDetails], situation: str) -> ReturnReading:
    prompt = ORDER_RETURN_READING_PROMPT.format(orders=_listing(orders), situation=situation)
    reader = get_chat_model().with_structured_output(ReturnReading).with_retry(stop_after_attempt=3)
    reading = await reader.ainvoke([SystemMessage(content=prompt), *state["messages"]])
    # The id comes from the model, so it is only ever used if it is one of the listed orders.
    if reading.order_id not in {o.order_id for o in orders}:
        reading = reading.model_copy(update={"order_id": None})
    return reading


def _start(order: OrderDetails) -> tuple[PendingReturn | None, ReturnResult]:
    options = return_options(order)
    if options.retention is not None:
        return (
            PendingReturn(order_id=order.order_id, stage=ReturnStage.OFFER),
            ReturnResult(outcome=ReturnOutcome.OFFER, order=order, offer=options.retention),
        )
    if options.can_cancel:
        return (
            PendingReturn(order_id=order.order_id, stage=ReturnStage.CONFIRM),
            ReturnResult(outcome=ReturnOutcome.CONFIRM_CANCEL, order=order),
        )
    return None, ReturnResult(outcome=ReturnOutcome.RETURN_LATER, order=order)


async def _cancel_or_explain(
    source, ids: dict, order: OrderDetails
) -> ReturnResult:
    if return_options(order).can_cancel:
        cancelled = await source.cancel_order(order_id=order.order_id, **ids)
        if cancelled is None:
            return ReturnResult(outcome=ReturnOutcome.NOT_AVAILABLE, order=order)
        return ReturnResult(outcome=ReturnOutcome.CANCELLED, order=cancelled)
    return ReturnResult(outcome=ReturnOutcome.RETURN_LATER, order=order)


# Everything this step says is fixed text, written here from the facts it just produced: no
# model, no order number, and no mention of cancelling in an offer (the cards carry the options and
# the buttons). So what the customer reads is exactly what happened.
def reply_for(result: ReturnResult) -> str:
    gift = " Your free gift is on its way too." if result.receipt and result.receipt.gift else ""
    match result.outcome:
        case ReturnOutcome.OFFER:
            return "I have your order here. Would you like to keep it and choose one of these instead?"
        case ReturnOutcome.FINAL_OFFER:
            return "Before you go: keep your order and we'll add a free gift on top of any of these."
        case ReturnOutcome.CONFIRM_CANCEL:
            return "I have your order here. Do you want me to go ahead?"
        case ReturnOutcome.CHOOSE_ORDER:
            return "I have a few orders here. Which one do you mean?"
        case ReturnOutcome.CANCELLED:
            return "Done: your order has been cancelled. Take care!"
        case ReturnOutcome.KEPT_WITH_REFUND if result.receipt:
            refund = _dollars(result.receipt.refund_cents or 0)
            return f"Done! I've refunded {refund} to your card and your order stays with you.{gift}"
        case ReturnOutcome.KEPT_WITH_CREDITS if result.receipt:
            points = f"{result.receipt.credit_points or 0:,}"
            return f"Done! I've added {points} points to your account and your order stays with you.{gift}"
        case ReturnOutcome.KEPT_WITH_FREE_ORDER:
            return f"Done! Your next order is free: use the code below at checkout. Your order stays with you.{gift}"
        case ReturnOutcome.KEPT_AS_IS:
            return "No problem, your order stays as it is."
        case ReturnOutcome.RETURN_LATER:
            return "Your order is on its way, so it can't be cancelled now. You can return it once it arrives."
        case ReturnOutcome.NOT_AVAILABLE:
            return "Sorry, that order can't be changed this way any more."
        case ReturnOutcome.NOTHING_TO_RETURN:
            return "I couldn't find an order that can be cancelled or returned."
    return ""


async def _continue(
    source, ids: dict, order: OrderDetails, pending: PendingReturn, choice: ReturnChoice
) -> tuple[PendingReturn | None, ReturnResult]:
    if not _actionable(order):
        return None, ReturnResult(outcome=ReturnOutcome.NOT_AVAILABLE, order=order)
    if choice is ReturnChoice.KEEP:
        return None, ReturnResult(outcome=ReturnOutcome.KEPT_AS_IS, order=order)
    offer = return_options(order).retention
    stage = pending.stage
    if choice is ReturnChoice.REJECT:
        if stage is ReturnStage.OFFER and offer is not None:
            # Declined once: one more try, with a gift. Declined again, it goes ahead.
            return (
                PendingReturn(order_id=order.order_id, stage=ReturnStage.FINAL_OFFER),
                ReturnResult(outcome=ReturnOutcome.FINAL_OFFER, order=order, offer=offer),
            )
        return None, await _cancel_or_explain(source, ids, order)
    in_offer = stage in (ReturnStage.OFFER, ReturnStage.FINAL_OFFER)
    if in_offer and choice in _TAKEN:
        retention_choice, outcome = _TAKEN[choice]
        receipt = await source.keep_order_with_retention(
            order_id=order.order_id,
            choice=retention_choice,
            with_gift=stage is ReturnStage.FINAL_OFFER,
            **ids,
        )
        if receipt is None:
            return None, ReturnResult(outcome=ReturnOutcome.NOT_AVAILABLE, order=order)
        return None, ReturnResult(outcome=outcome, order=order, receipt=receipt)
    # Not understood (or an offer answer to a plain confirmation): ask again, same place.
    again_outcome = {
        ReturnStage.OFFER: ReturnOutcome.OFFER,
        ReturnStage.FINAL_OFFER: ReturnOutcome.FINAL_OFFER,
    }.get(stage, ReturnOutcome.CONFIRM_CANCEL)
    again = ReturnResult(outcome=again_outcome, order=order, offer=offer if in_offer else None)
    return pending, again


def _answer(pending: PendingReturn | None, result: ReturnResult) -> dict:
    """The state update, with the reply: no model words what this step says."""
    return {
        "pending_return": pending,
        "return_result": result,
        "messages": [AIMessage(content=reply_for(result))],
    }


async def order_return_node(state: AgentState) -> dict:
    customer_id, tenant_id = state.get("customer_id"), state.get("tenant_id")
    if customer_id is None or tenant_id is None:
        raise ValueError("rejecting an order needs a verified customer")
    source = get_order_source()
    ids = {"tenant_id": uuid.UUID(tenant_id), "customer_id": uuid.UUID(customer_id)}
    orders = await source.list_orders(**ids)
    by_id = {o.order_id: o for o in orders}
    pending = state.get("pending_return")

    if pending is not None and pending.order_id in by_id:
        order = by_id[pending.order_id]
        situation = {
            ReturnStage.OFFER: OFFER_SITUATION,
            ReturnStage.FINAL_OFFER: FINAL_OFFER_SITUATION,
        }.get(pending.stage, CONFIRM_SITUATION).format(order_id=order.order_id)
        reading = await _read(state, [order], situation)
        new_pending, result = await _continue(source, ids, order, pending, reading.choice)
        return _answer(new_pending, result)

    candidates = [o for o in orders if _actionable(o)]
    if not candidates:
        return {
            "pending_return": None,
            "return_result": ReturnResult(outcome=ReturnOutcome.NOTHING_TO_RETURN),
        }
    order = candidates[0] if len(candidates) == 1 else None
    if order is None:
        reading = await _read(state, candidates, NO_PENDING_SITUATION)
        order = by_id.get(reading.order_id) if reading.order_id else None
    if order is None:
        result = ReturnResult(outcome=ReturnOutcome.CHOOSE_ORDER, candidates=candidates)
        return {"pending_return": None, "return_result": result}
    new_pending, result = _start(order)
    return _answer(new_pending, result)
