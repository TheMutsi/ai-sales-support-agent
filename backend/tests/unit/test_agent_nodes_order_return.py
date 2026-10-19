"""The order_return step: what the model reads decides nothing by itself. Rules, the orders
interface and the conversation's pending state are real; the model and the shop are fakes."""

import uuid
from datetime import UTC, datetime

import pytest

from app.agent.nodes import order_return as module
from app.agent.nodes.order_return import order_return_node
from app.business.returns import retention_offer
from app.schemas.agent import ReturnChoice, ReturnReading
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    PendingReturn,
    RetentionChoice,
    RetentionReceipt,
    ReturnOutcome,
    ReturnStage,
)

TENANT, CUSTOMER = str(uuid.uuid4()), str(uuid.uuid4())
OPEN_30, OPEN_70, SHIPPED_70, SHIPPED_30 = (c * 20 for c in "ABCD")


def _order(order_id, status, cents, retention=None) -> OrderDetails:
    return OrderDetails(
        order_id=order_id, customer_email="mail1@gmail.com", plan_slug="starter",
        amount_cents=cents, currency="usd", status=status,
        created_at=datetime(2026, 10, 1, tzinfo=UTC), retention=retention,
    )


class FakeShop:
    """An in-memory shop that follows the same rules the real source enforces."""

    def __init__(self, *orders: OrderDetails):
        self.orders = {o.order_id: o for o in orders}
        self.calls: list[tuple] = []

    async def list_orders(self, *, tenant_id, customer_id, limit=10):
        return list(self.orders.values())

    async def cancel_order(self, *, tenant_id, customer_id, order_id):
        self.calls.append(("cancel", order_id))
        order = self.orders[order_id]
        if order.status is not OrderStatus.OPEN or order.retention:
            return None
        self.orders[order_id] = order.model_copy(update={"status": OrderStatus.CANCELLED})
        return self.orders[order_id]

    async def keep_order_with_retention(self, *, tenant_id, customer_id, order_id, choice, with_gift=False):
        self.calls.append(("keep", order_id, choice))
        order = self.orders[order_id]
        offer = retention_offer(order.amount_cents)
        if offer is None or order.retention:
            return None
        receipt = RetentionReceipt(
            order_id=order_id, choice=choice,
            refund_cents=offer.refund_cents if choice is RetentionChoice.REFUND else None,
            credit_cents=offer.credit_cents if choice is RetentionChoice.CREDITS else None,
            gift="Chai Jelly" if with_gift else None,
        )
        self.orders[order_id] = order.model_copy(update={"retention": receipt})
        return receipt


class FakeReader:
    def __init__(self, reading: ReturnReading | None):
        self.reading, self.asked = reading, 0

    def with_structured_output(self, schema):
        return self

    def with_retry(self, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.asked += 1
        assert self.reading is not None, "the model must not be asked here"
        return self.reading


@pytest.fixture
def setup(monkeypatch):
    def install(*orders, reading=None):
        shop, reader = FakeShop(*orders), FakeReader(reading)
        monkeypatch.setattr(module, "get_order_source", lambda: shop)
        monkeypatch.setattr(module, "get_chat_model", lambda: reader)
        return shop, reader

    return install


def _state(pending=None) -> dict:
    return {"tenant_id": TENANT, "customer_id": CUSTOMER, "messages": [], "pending_return": pending}


def _pending(order_id, stage) -> PendingReturn:
    return PendingReturn(order_id=order_id, stage=stage)


async def _run(setup, orders, choice=None, pending=None, order_id=None):
    """The node against a shop holding `orders`; the model (if asked) reads `choice`."""
    reading = None if choice is None else ReturnReading(choice=choice, order_id=order_id)
    shop, reader = setup(*orders, reading=reading)
    result = await order_return_node(_state(pending))
    return result, shop, reader


OPEN70, OPEN30 = _order(OPEN_70, OrderStatus.OPEN, 6999), _order(OPEN_30, OrderStatus.OPEN, 2999)
SHIPPED70 = _order(SHIPPED_70, OrderStatus.IN_DELIVERY, 6999)
SHIPPED30 = _order(SHIPPED_30, OrderStatus.IN_DELIVERY, 2999)
OFFER, CONFIRM, FINAL = ReturnStage.OFFER, ReturnStage.CONFIRM, ReturnStage.FINAL_OFFER


@pytest.mark.asyncio
async def test_asking_to_reject_the_69_99_open_order_makes_the_offer_and_changes_nothing(setup):
    result, shop, reader = await _run(setup, [OPEN70])

    returned = result["return_result"]
    assert returned.outcome is ReturnOutcome.OFFER
    assert (returned.offer.refund_cents, returned.offer.credit_cents) == (1400, 2100)
    assert result["pending_return"] == _pending(OPEN_70, OFFER)
    assert shop.calls == [] and reader.asked == 0  # one candidate: nothing to ask the model


@pytest.mark.asyncio
async def test_the_29_99_open_order_asks_for_confirmation_before_cancelling(setup):
    result, shop, _ = await _run(setup, [OPEN30])

    assert result["return_result"].outcome is ReturnOutcome.CONFIRM_CANCEL
    assert result["pending_return"] == _pending(OPEN_30, CONFIRM) and shop.calls == []


@pytest.mark.asyncio
async def test_an_order_in_delivery_cannot_be_rejected_only_returned_later(setup):
    result, shop, _ = await _run(setup, [SHIPPED30])

    assert result["return_result"].outcome is ReturnOutcome.RETURN_LATER
    assert result["pending_return"] is None and shop.calls == []


@pytest.mark.asyncio
async def test_the_69_99_order_in_delivery_gets_the_offer_too(setup):
    result, _, _ = await _run(setup, [SHIPPED70])

    assert result["return_result"].outcome is ReturnOutcome.OFFER
    assert result["pending_return"] == _pending(SHIPPED_70, OFFER)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("choice", "outcome", "refund", "points"),
    [
        (ReturnChoice.REFUND, ReturnOutcome.KEPT_WITH_REFUND, 1400, None),
        (ReturnChoice.CREDITS, ReturnOutcome.KEPT_WITH_CREDITS, None, 2100),
    ],
)
async def test_taking_the_offer_keeps_the_order_and_records_what_was_chosen(
    setup, choice, outcome, refund, points
):
    result, shop, _ = await _run(setup, [OPEN70], choice, _pending(OPEN_70, OFFER))

    receipt = result["return_result"].receipt
    assert result["return_result"].outcome is outcome and result["pending_return"] is None
    assert (receipt.refund_cents, receipt.credit_cents) == (refund, points)
    assert shop.orders[OPEN_70].status is OrderStatus.OPEN  # kept: nothing is cancelled
    assert [call[0] for call in shop.calls] == ["keep"]


@pytest.mark.asyncio
async def test_declining_the_offer_once_makes_the_last_offer_with_a_gift_and_changes_nothing(setup):
    result, shop, _ = await _run(setup, [OPEN70], ReturnChoice.REJECT, _pending(OPEN_70, OFFER))

    assert result["return_result"].outcome is ReturnOutcome.FINAL_OFFER
    assert result["pending_return"] == _pending(OPEN_70, FINAL)
    assert shop.calls == [] and shop.orders[OPEN_70].status is OrderStatus.OPEN


@pytest.mark.asyncio
async def test_declining_the_last_offer_cancels_an_open_order(setup):
    result, shop, _ = await _run(setup, [OPEN70], ReturnChoice.REJECT, _pending(OPEN_70, FINAL))

    assert result["return_result"].outcome is ReturnOutcome.CANCELLED
    assert shop.orders[OPEN_70].status is OrderStatus.CANCELLED and result["pending_return"] is None


@pytest.mark.asyncio
async def test_declining_the_last_offer_on_an_order_in_delivery_leaves_it_for_a_later_return(setup):
    result, shop, _ = await _run(setup, [SHIPPED70], ReturnChoice.REJECT, _pending(SHIPPED_70, FINAL))

    assert result["return_result"].outcome is ReturnOutcome.RETURN_LATER
    assert shop.calls == [] and shop.orders[SHIPPED_70].status is OrderStatus.IN_DELIVERY


@pytest.mark.asyncio
async def test_confirming_cancels_and_changing_their_mind_keeps_the_order(setup):
    cancelled, shop, _ = await _run(setup, [OPEN30], ReturnChoice.REJECT, _pending(OPEN_30, CONFIRM))
    kept, shop2, _ = await _run(setup, [OPEN30], ReturnChoice.KEEP, _pending(OPEN_30, CONFIRM))

    assert cancelled["return_result"].outcome is ReturnOutcome.CANCELLED
    assert shop.orders[OPEN_30].status is OrderStatus.CANCELLED
    assert kept["return_result"].outcome is ReturnOutcome.KEPT_AS_IS and shop2.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("order", "stage", "choice", "outcome"),
    [
        (OPEN70, OFFER, ReturnChoice.UNCLEAR, ReturnOutcome.OFFER),
        (OPEN30, CONFIRM, ReturnChoice.UNCLEAR, ReturnOutcome.CONFIRM_CANCEL),
        # An offer answer to a plain confirmation has nothing to apply.
        (OPEN30, CONFIRM, ReturnChoice.REFUND, ReturnOutcome.CONFIRM_CANCEL),
    ],
)
async def test_an_answer_that_does_not_fit_asks_again_in_the_same_place(setup, order, stage, choice, outcome):
    pending = _pending(order.order_id, stage)

    result, shop, _ = await _run(setup, [order], choice, pending)

    assert result["return_result"].outcome is outcome
    assert result["pending_return"] == pending and shop.calls == []


@pytest.mark.asyncio
async def test_with_several_orders_the_customer_picks_one_and_a_made_up_id_is_ignored(setup):
    asked, _, _ = await _run(setup, [OPEN30, OPEN70], ReturnChoice.REJECT, order_id="Z" * 20)
    chosen, _, _ = await _run(setup, [OPEN30, OPEN70], ReturnChoice.REJECT, order_id=OPEN_70)

    assert asked["return_result"].outcome is ReturnOutcome.CHOOSE_ORDER
    assert {o.order_id for o in asked["return_result"].candidates} == {OPEN_30, OPEN_70}
    assert chosen["return_result"].outcome is ReturnOutcome.OFFER
    assert chosen["return_result"].order.order_id == OPEN_70


@pytest.mark.asyncio
async def test_an_order_already_kept_or_cancelled_is_not_offered_again(setup):
    kept = RetentionReceipt(order_id=OPEN_70, choice=RetentionChoice.REFUND, refund_cents=1400)
    orders = [OPEN70.model_copy(update={"retention": kept}), _order(OPEN_30, OrderStatus.CANCELLED, 2999)]

    result, _, _ = await _run(setup, orders)

    assert result["return_result"].outcome is ReturnOutcome.NOTHING_TO_RETURN


@pytest.mark.asyncio
async def test_a_stale_pending_return_for_an_order_that_changed_does_nothing_and_clears(setup):
    cancelled = _order(OPEN_70, OrderStatus.CANCELLED, 6999)

    result, shop, _ = await _run(setup, [cancelled], ReturnChoice.REFUND, _pending(OPEN_70, OFFER))

    assert result["pending_return"] is None and shop.calls == []
    assert result["return_result"].outcome is ReturnOutcome.NOT_AVAILABLE


@pytest.mark.asyncio
async def test_it_needs_a_verified_customer():
    with pytest.raises(ValueError, match="verified customer"):
        await order_return_node({"tenant_id": TENANT, "customer_id": None, "messages": []})


@pytest.mark.asyncio
async def test_the_gift_comes_only_with_the_last_offer(setup):
    first, _, _ = await _run(setup, [OPEN70], ReturnChoice.CREDITS, _pending(OPEN_70, OFFER))
    last, _, _ = await _run(setup, [OPEN70], ReturnChoice.CREDITS, _pending(OPEN_70, FINAL))

    assert first["return_result"].receipt.gift is None
    assert last["return_result"].receipt.gift == "Chai Jelly"


@pytest.mark.asyncio
async def test_every_reply_is_fixed_text_with_no_id_and_an_offer_never_says_cancel(setup):
    offer, _, _ = await _run(setup, [OPEN70])
    final, _, _ = await _run(setup, [OPEN70], ReturnChoice.REJECT, _pending(OPEN_70, OFFER))
    confirm, _, _ = await _run(setup, [OPEN30])
    cancelled, _, _ = await _run(setup, [OPEN70], ReturnChoice.REJECT, _pending(OPEN_70, FINAL))

    for update in (offer, final, confirm):
        text = update["messages"][0].content
        assert not any(ch.isdigit() for ch in text)
        assert "cancel" not in text.lower() and "reject" not in text.lower()
    assert cancelled["messages"][0].content == "Done: your order has been cancelled. Take care!"
    for update in (offer, final, confirm, cancelled):
        assert OPEN_70 not in update["messages"][0].content and OPEN_30 not in update["messages"][0].content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "choice", "expected"),
    [
        (OFFER, ReturnChoice.REFUND, "Done! I've refunded $14.00 to your card and your order stays with you."),
        (OFFER, ReturnChoice.CREDITS, "Done! I've added $21.00 in credits to your account and your order stays with you."),
        (FINAL, ReturnChoice.CREDITS, "Done! I've added $21.00 in credits to your account and your order stays with you. Your free gift is on its way too."),
    ],
)
async def test_taking_an_offer_is_confirmed_with_the_exact_amounts_and_the_gift(setup, stage, choice, expected):
    result, _, _ = await _run(setup, [OPEN70], choice, _pending(OPEN_70, stage))

    assert result["messages"][0].content == expected


@pytest.mark.asyncio
async def test_the_other_outcomes_have_their_own_fixed_replies(setup):
    from app.agent.nodes.order_return import reply_for
    from app.schemas.orders import ReturnResult

    replies = {outcome: reply_for(ReturnResult(outcome=outcome)) for outcome in ReturnOutcome}

    assert all(replies[o] for o in ReturnOutcome if o not in (ReturnOutcome.KEPT_WITH_REFUND, ReturnOutcome.KEPT_WITH_CREDITS))
    assert "go ahead" in replies[ReturnOutcome.CONFIRM_CANCEL] and "once it arrives" in replies[ReturnOutcome.RETURN_LATER]
