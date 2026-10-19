"""A click carries an action, not text: the request shape, the check that it was offered, and
where the graph sends it."""

import uuid

import pytest
from pydantic import ValidationError

from app.agent.names import Node
from app.agent.routing import route_start
from app.auth.scopes import Scope
from app.chat.actions import offered_card
from app.schemas.cards import ActionCard, CardAction, DividerCard
from app.schemas.chat import ActionInput, ChatRequest


def _request(entry: dict) -> dict:
    return {"message_id": str(uuid.uuid4()), "input": entry}


def test_a_click_is_an_action_with_no_text_of_its_own():
    request = ChatRequest.model_validate(_request({"type": "action", "action": "take_refund"}))

    assert isinstance(request.input, ActionInput) and request.input.action is CardAction.TAKE_REFUND


@pytest.mark.parametrize(
    "entry",
    [
        {"type": "action", "action": "refund_everything"},  # not in the closed set
        {"type": "action"},
        {"type": "action", "action": "choose_order", "order_id": "x" * 65},
        {"type": "text"},
        {"type": "voice", "message": "hi"},
    ],
)
def test_a_malformed_input_is_rejected_not_answered(entry):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(_request(entry))


def test_text_still_arrives_as_a_plain_message_for_widgets_already_loaded():
    request = ChatRequest.model_validate({"message": "hola", "message_id": str(uuid.uuid4())})

    assert request.input.type == "text" and request.input.message == "hola"


def _card(action, order_id=None) -> ActionCard:
    return ActionCard(id="c", title="t", message="what it says", action=action, order_id=order_id)


def test_a_click_is_offered_only_if_the_same_action_and_order_were_shown():
    cards = [DividerCard(id="d"), _card(CardAction.CHOOSE_ORDER, "A" * 20), _card(CardAction.KEEP_ORDER), _card(None)]

    assert offered_card(cards, CardAction.KEEP_ORDER, None).message == "what it says"
    assert offered_card(cards, CardAction.CHOOSE_ORDER, "A" * 20) is not None
    assert offered_card(cards, CardAction.CHOOSE_ORDER, "B" * 20) is None  # another order
    assert offered_card(cards, CardAction.CHOOSE_ORDER, None) is None
    assert offered_card(cards, CardAction.TAKE_REFUND, None) is None  # never shown
    assert offered_card([], CardAction.KEEP_ORDER, None) is None


def _state(**kw) -> dict:
    return {"action": CardAction.KEEP_ORDER, "customer_id": "c", "scopes": [Scope.REFUND_REQUEST.value], **kw}


def test_a_click_from_a_verified_customer_skips_the_filter_and_the_classifier():
    assert route_start(_state()) == Node.ORDER_RETURN


@pytest.mark.parametrize(
    "state",
    [
        _state(action=None),  # written text
        _state(customer_id=None),
        _state(scopes=[]),
    ],
)
def test_text_and_clicks_without_a_customer_take_the_ordinary_path(state):
    assert route_start(state) == Node.INPUT_GUARDRAIL
