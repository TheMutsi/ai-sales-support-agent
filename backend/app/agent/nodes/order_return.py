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

from langchain_core.messages import SystemMessage

from app.agent.prompts.order_return import (
    CONFIRM_SITUATION,
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
        f"- order_id {o.order_id}: {_dollars(o.amount_cents)}, status {o.status.value}"
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


async def _continue(
    source, ids: dict, order: OrderDetails, pending: PendingReturn, choice: ReturnChoice
) -> tuple[PendingReturn | None, ReturnResult]:
    if not _actionable(order):
        return None, ReturnResult(outcome=ReturnOutcome.NOT_AVAILABLE, order=order)
    if choice is ReturnChoice.KEEP:
        return None, ReturnResult(outcome=ReturnOutcome.KEPT_AS_IS, order=order)
    if choice is ReturnChoice.REJECT:
        return None, await _cancel_or_explain(source, ids, order)
    offered = pending.stage is ReturnStage.OFFER
    if offered and choice in _TAKEN:
        retention_choice, outcome = _TAKEN[choice]
        receipt = await source.keep_order_with_retention(
            order_id=order.order_id, choice=retention_choice, **ids
        )
        if receipt is None:
            return None, ReturnResult(outcome=ReturnOutcome.NOT_AVAILABLE, order=order)
        return None, ReturnResult(outcome=outcome, order=order, receipt=receipt)
    # Not understood (or an offer answer to a plain confirmation): ask again, same place.
    again = ReturnResult(
        outcome=ReturnOutcome.OFFER if offered else ReturnOutcome.CONFIRM_CANCEL,
        order=order,
        offer=return_options(order).retention if offered else None,
    )
    return pending, again


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
        situation = (OFFER_SITUATION if pending.stage is ReturnStage.OFFER else CONFIRM_SITUATION).format(
            order_id=order.order_id
        )
        reading = await _read(state, [order], situation)
        new_pending, result = await _continue(source, ids, order, pending, reading.choice)
        return {"pending_return": new_pending, "return_result": result}

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
    return {"pending_return": new_pending, "return_result": result}
