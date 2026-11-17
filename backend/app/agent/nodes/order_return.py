import uuid

from langchain_core.messages import AIMessage, SystemMessage

from app.agent.prompts.order_return import (
    CHECK_SITUATION,
    CONFIRM_SITUATION,
    FINAL_OFFER_SITUATION,
    NO_PENDING_SITUATION,
    OFFER_SITUATION,
    ORDER_RETURN_READING_PROMPT,
)
from app.agent.pushback import last_reply_in
from app.agent.state import AgentState
from app.business.returns import return_options
from app.core.llm import get_chat_model
from app.orders.factory import get_order_source
from app.schemas.agent import Intent, ReturnChoice, ReturnReading
from app.schemas.cards import CardAction
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    PendingReturn,
    RetentionChoice,
    ReturnOutcome,
    ReturnResult,
    ReturnStage,
)

_RETENTION_BY_CHOICE = {
    ReturnChoice.REFUND: (RetentionChoice.REFUND, ReturnOutcome.KEPT_WITH_REFUND),
    ReturnChoice.CREDITS: (RetentionChoice.CREDITS, ReturnOutcome.KEPT_WITH_CREDITS),
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
    return _without_unlisted_order(reading, orders)


def _without_unlisted_order(reading: ReturnReading, orders: list[OrderDetails]) -> ReturnReading:
    if reading.order_id not in {o.order_id for o in orders}:
        return reading.model_copy(update={"order_id": None})
    return reading


def _ask_if_this_is_the_order(order: OrderDetails) -> tuple[PendingReturn, ReturnResult]:
    return (
        PendingReturn(order_id=order.order_id, stage=ReturnStage.CHECK),
        ReturnResult(outcome=ReturnOutcome.CONFIRM_ORDER, order=order),
    )


_CHOICE_BY_ACTION = {
    CardAction.CONFIRM_ORDER: ReturnChoice.REJECT,
    CardAction.CONFIRM_CANCEL: ReturnChoice.REJECT,
    CardAction.DECLINE_OFFER: ReturnChoice.REJECT,
    CardAction.CHOOSE_ORDER: ReturnChoice.REJECT,
    CardAction.TAKE_REFUND: ReturnChoice.REFUND,
    CardAction.TAKE_CREDITS: ReturnChoice.CREDITS,
    CardAction.KEEP_ORDER: ReturnChoice.KEEP,
}
_OFFER_ACTIONS = {CardAction.TAKE_REFUND, CardAction.TAKE_CREDITS, CardAction.DECLINE_OFFER}
_ACTIONS_BY_STAGE: dict[ReturnStage | None, set[CardAction]] = {
    None: {CardAction.CHOOSE_ORDER},
    ReturnStage.CHECK: {CardAction.CONFIRM_ORDER, CardAction.KEEP_ORDER},
    ReturnStage.OFFER: _OFFER_ACTIONS,
    ReturnStage.FINAL_OFFER: _OFFER_ACTIONS,
    ReturnStage.CONFIRM: {CardAction.CONFIRM_CANCEL, CardAction.KEEP_ORDER},
}


def _reading_from_click(
    state: AgentState, orders: list[OrderDetails], stage: ReturnStage | None
) -> ReturnReading:
    action = state["action"]
    if action not in _ACTIONS_BY_STAGE[stage]:
        return ReturnReading(choice=ReturnChoice.UNCLEAR, order_id=None)
    order_id = state.get("action_order_id") if action is CardAction.CHOOSE_ORDER else None
    if order_id not in {o.order_id for o in orders}:
        order_id = None
    return ReturnReading(choice=_CHOICE_BY_ACTION[action], order_id=order_id)


async def _reading(
    state: AgentState, orders: list[OrderDetails], situation: str, stage: ReturnStage | None
) -> ReturnReading:
    if state.get("action") is not None:
        return _reading_from_click(state, orders, stage)
    return await _read(state, orders, situation)


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


async def _cancel_or_explain(source, ids: dict, order: OrderDetails) -> ReturnResult:
    if return_options(order).can_cancel:
        cancelled = await source.cancel_order(order_id=order.order_id, **ids)
        if cancelled is None:
            return ReturnResult(outcome=ReturnOutcome.NOT_AVAILABLE, order=order)
        return ReturnResult(outcome=ReturnOutcome.CANCELLED, order=cancelled)
    return ReturnResult(outcome=ReturnOutcome.RETURN_LATER, order=order)


def reply_for(result: ReturnResult) -> str:
    gift = " Your free gift is on its way too." if result.receipt and result.receipt.gift else ""
    match result.outcome:
        case ReturnOutcome.OFFER:
            return (
                "I have your order here. Would you like to keep it and choose one of these instead?"
            )
        case ReturnOutcome.FINAL_OFFER:
            return "Before you go: keep your order and we'll add a free gift on top of either of these."
        case ReturnOutcome.CONFIRM_ORDER:
            return "Is this the order you want to cancel? If it's another one, just tell me which."
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
            credits = _dollars(result.receipt.credit_cents or 0)
            return f"Done! I've added {credits} in credits to your account and your order stays with you.{gift}"
        case ReturnOutcome.KEPT_AS_IS:
            return "No problem, your order stays as it is."
        case ReturnOutcome.RETURN_LATER:
            return "Your order is on its way, so it can't be cancelled now. You can return it once it arrives."
        case ReturnOutcome.NOT_AVAILABLE:
            return "Sorry, that order can't be changed this way any more."
        case ReturnOutcome.NOTHING_TO_RETURN:
            return "I couldn't find an order that can be cancelled or returned."
    return ""


_REPLIES_THAT_SAY_NO = frozenset(
    reply_for(ReturnResult(outcome=outcome))
    for outcome in (
        ReturnOutcome.RETURN_LATER,
        ReturnOutcome.NOT_AVAILABLE,
        ReturnOutcome.NOTHING_TO_RETURN,
    )
)


def _escalate(orders: list[OrderDetails]) -> dict:
    on_its_way = [o for o in orders if o.status is OrderStatus.IN_DELIVERY]
    unambiguous = bool(on_its_way) and not any(return_options(o).can_cancel for o in orders)
    return {
        "pending_return": None,
        "return_result": ReturnResult(
            outcome=ReturnOutcome.ESCALATED, order=on_its_way[0] if unambiguous else None
        ),
        "intent": Intent.HUMAN_ESCALATION,
        "return_reading": None,
    }


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
            return (
                PendingReturn(order_id=order.order_id, stage=ReturnStage.FINAL_OFFER),
                ReturnResult(outcome=ReturnOutcome.FINAL_OFFER, order=order, offer=offer),
            )
        return None, await _cancel_or_explain(source, ids, order)
    in_offer = stage in (ReturnStage.OFFER, ReturnStage.FINAL_OFFER)
    if in_offer and choice in _RETENTION_BY_CHOICE:
        retention_choice, outcome = _RETENTION_BY_CHOICE[choice]
        receipt = await source.keep_order_with_retention(
            order_id=order.order_id,
            choice=retention_choice,
            with_gift=stage is ReturnStage.FINAL_OFFER,
            **ids,
        )
        if receipt is None:
            return None, ReturnResult(outcome=ReturnOutcome.NOT_AVAILABLE, order=order)
        return None, ReturnResult(outcome=outcome, order=order, receipt=receipt)
    again_outcome = {
        ReturnStage.OFFER: ReturnOutcome.OFFER,
        ReturnStage.FINAL_OFFER: ReturnOutcome.FINAL_OFFER,
    }.get(stage, ReturnOutcome.CONFIRM_CANCEL)
    again = ReturnResult(outcome=again_outcome, order=order, offer=offer if in_offer else None)
    return pending, again


def _answer(
    pending: PendingReturn | None, result: ReturnResult, reading: ReturnReading | None = None
) -> dict:
    return {
        "pending_return": pending,
        "return_result": result,
        "messages": [AIMessage(content=reply_for(result))],
        "intent": Intent.ORDER_RETURN,
        "return_reading": reading.choice if reading else None,
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

    after_no = None
    written_right_after_a_no = (
        pending is None
        and state.get("action") is None
        and last_reply_in(state["messages"], _REPLIES_THAT_SAY_NO)
    )
    if written_right_after_a_no:
        actionable = [o for o in orders if _actionable(o)]
        if not actionable:
            return _escalate(orders)
        after_no = await _read(state, actionable, NO_PENDING_SITUATION)
        if after_no.order_id is None:
            return _escalate(orders)

    if pending is not None and pending.order_id in by_id and pending.stage is ReturnStage.CHECK:
        order = by_id[pending.order_id]
        candidates = [o for o in orders if _actionable(o)] or [order]
        reading = await _reading(
            state, candidates, CHECK_SITUATION.format(order_id=order.order_id), pending.stage
        )
        named = by_id.get(reading.order_id) if reading.order_id else None
        if named is not None and named.order_id != order.order_id and _actionable(named):
            return _answer(
                *_start(named), reading=reading
            )
        if reading.choice is ReturnChoice.KEEP:
            return _answer(
                None, ReturnResult(outcome=ReturnOutcome.KEPT_AS_IS, order=order), reading
            )
        if reading.choice is ReturnChoice.REJECT:
            return _answer(*_start(order), reading=reading)
        return _answer(*_ask_if_this_is_the_order(order), reading=reading)

    if pending is not None and pending.order_id in by_id:
        order = by_id[pending.order_id]
        situation = {
            ReturnStage.OFFER: OFFER_SITUATION,
            ReturnStage.FINAL_OFFER: FINAL_OFFER_SITUATION,
        }.get(pending.stage, CONFIRM_SITUATION).format(order_id=order.order_id)
        reading = await _reading(state, [order], situation, pending.stage)
        new_pending, result = await _continue(source, ids, order, pending, reading.choice)
        return _answer(new_pending, result, reading)

    candidates = [o for o in orders if _actionable(o)]
    if not candidates:
        return _answer(None, ReturnResult(outcome=ReturnOutcome.NOTHING_TO_RETURN))
    order = candidates[0] if len(candidates) == 1 else None
    reading = after_no
    if order is None and reading is None:
        reading = await _reading(state, candidates, NO_PENDING_SITUATION, None)
    if order is None:
        order = by_id.get(reading.order_id) if reading.order_id else None
    if order is None:
        result = ReturnResult(outcome=ReturnOutcome.CHOOSE_ORDER, candidates=candidates)
        return _answer(None, result, reading)
    customer_named_it = reading is not None
    if not customer_named_it:
        return _answer(*_ask_if_this_is_the_order(order))
    return _answer(*_start(order), reading=reading)
