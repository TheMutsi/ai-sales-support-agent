"""What is recorded for a turn of a return: built only from what the steps did."""

import uuid
from datetime import UTC, datetime

from app.chat.return_events import build_return_event
from app.chat.turns import TurnAction, TurnStart
from app.schemas.agent import ReturnChoice
from app.schemas.cards import CardAction
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    PendingReturn,
    RetentionChoice,
    RetentionOffer,
    RetentionReceipt,
    ReturnOutcome,
    ReturnResult,
    ReturnStage,
)

ORDER = OrderDetails(
    order_id="A" * 20, customer_email="m@x.com", plan_slug="starter", amount_cents=6999, currency="usd",
    status=OrderStatus.OPEN, created_at=datetime(2026, 10, 1, tzinfo=UTC),
)
IDS = {"tenant_id": uuid.uuid4(), "conversation_id": uuid.uuid4(), "customer_id": uuid.uuid4()}


def _event(final_state, turn):
    return build_return_event(
        final_state, turn=turn, identity_level="store_login", model="m", app_version="v", duration_ms=12, **IDS
    )


def test_a_turn_that_did_not_go_through_the_return_step_records_nothing():
    assert _event({"messages": []}, TurnStart(TurnAction.RUN, user_seq=1)) is None


def test_a_click_that_declines_the_offer_records_where_they_were_and_what_came_next():
    turn = TurnStart(
        TurnAction.RUN, user_seq=7, click=CardAction.DECLINE_OFFER,
        pending_return=PendingReturn(order_id=ORDER.order_id, stage=ReturnStage.OFFER),
    )
    state = {
        "return_result": ReturnResult(
            outcome=ReturnOutcome.FINAL_OFFER, order=ORDER, offer=RetentionOffer(refund_cents=1400, credit_cents=2100)
        ),
        "pending_return": PendingReturn(order_id=ORDER.order_id, stage=ReturnStage.FINAL_OFFER),
        "return_reading": ReturnChoice.REJECT,
    }

    event = _event(state, turn)

    assert event | {} == {
        **IDS, "identity_level": "store_login", "user_seq": 7, "input_type": "action",
        "action": "decline_offer", "action_order_id": None, "reading": "reject",
        "stage_before": "offer", "stage_after": "final_offer", "outcome": "final_offer",
        "order_id": ORDER.order_id, "order_status": "open", "order_amount_cents": 6999, "candidates": 0,
        "offer_refund_cents": 1400, "offer_credit_cents": 2100, "taken_refund_cents": None,
        "taken_credit_cents": None, "gift": None, "model": "m", "app_version": "v", "duration_ms": 12,
    }


def test_written_words_and_what_was_taken_with_the_gift_are_recorded():
    receipt = RetentionReceipt(
        order_id=ORDER.order_id, choice=RetentionChoice.CREDITS, credit_cents=2100, gift="the gift"
    )
    state = {
        "return_result": ReturnResult(outcome=ReturnOutcome.KEPT_WITH_CREDITS, order=ORDER, receipt=receipt),
        "pending_return": None,
        "return_reading": ReturnChoice.CREDITS,
    }

    event = _event(state, TurnStart(TurnAction.RUN, user_seq=9))

    assert (event["input_type"], event["action"], event["reading"]) == ("text", None, "credits")
    assert (event["stage_before"], event["stage_after"]) == (None, None)  # finished
    assert (event["taken_credit_cents"], event["taken_refund_cents"], event["gift"]) == (2100, None, "the gift")


def test_choosing_among_orders_records_how_many_were_shown_and_no_order_yet():
    state = {"return_result": ReturnResult(outcome=ReturnOutcome.CHOOSE_ORDER, candidates=[ORDER, ORDER])}

    event = _event(state, TurnStart(TurnAction.RUN, user_seq=2))

    assert event["candidates"] == 2 and event["order_id"] is None and event["order_amount_cents"] is None
