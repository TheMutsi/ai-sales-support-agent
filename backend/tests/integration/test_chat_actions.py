"""A button click against a real conversation: offered or not, what is stored, and retries."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api.chat import ActionNotOffered, _open_turn
from app.auth.conversations import create_anonymous
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token, verify_session_token
from app.chat.turns import TurnAction, finish_turn, list_messages
from app.core.config import get_settings
from app.db.models import Tenant
from app.db.session import SessionLocal
from app.schemas.cards import ActionCard, CardAction
from app.schemas.chat import ChatRequest

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
ORDER = "A" * 20


@pytest.fixture
def setup(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        conversation = create_anonymous(db, tenant_id=tenant.id, now=NOW)
        db.commit()
        token, _ = issue_session_token(
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            customer_id=None,
            level=IdentityLevel.ANONYMOUS,
            signing_key=get_settings().session_signing_key,
            ttl=timedelta(hours=1),
        )
        yield verify_session_token(token, get_settings().session_signing_key), conversation.id


def _offer(conversation_id, *cards):
    """A reply that offered these buttons, as the chat stores it."""
    with SessionLocal() as db:
        turn = _open_turn_text(db, conversation_id)
        finish_turn(db, conversation_id=conversation_id, turn=turn, content="Which?", now=NOW, cards=list(cards))


def _open_turn_text(db, conversation_id):
    from app.chat.turns import begin_turn

    return begin_turn(db, conversation_id=conversation_id, client_message_id=uuid.uuid4(), content="cancel", now=NOW)


def _click(action, order_id=None) -> ChatRequest:
    return ChatRequest.model_validate(
        {"message_id": str(uuid.uuid4()), "input": {"type": "action", "action": action, "order_id": order_id}}
    )


KEEP = ActionCard(id="k", title="Keep", message="No, keep my order", action=CardAction.KEEP_ORDER)
PICK = ActionCard(
    id="p", title="One", message="I mean the Starter order", action=CardAction.CHOOSE_ORDER, order_id=ORDER
)


def test_an_offered_click_runs_and_says_what_its_card_says(setup):
    claims, conversation_id = setup
    _offer(conversation_id, KEEP)

    turn = _open_turn(claims, _click("keep_order"))

    assert turn.action is TurnAction.RUN
    assert turn.click is CardAction.KEEP_ORDER and turn.user_text == "No, keep my order"
    with SessionLocal() as db:
        assert list_messages(db, conversation_id=conversation_id)[-1].content == "No, keep my order"


@pytest.mark.parametrize(
    ("action", "order_id"),
    [("take_refund", None), ("choose_order", "B" * 20), ("choose_order", None)],
)
def test_a_click_that_was_not_offered_stores_nothing_and_returns_the_open_question(setup, action, order_id):
    claims, conversation_id = setup
    _offer(conversation_id, PICK)
    with SessionLocal() as db:
        before = len(list_messages(db, conversation_id=conversation_id))

    with pytest.raises(ActionNotOffered) as missed:
        _open_turn(claims, _click(action, order_id))

    assert [c.id for c in missed.value.cards] == ["p"]
    with SessionLocal() as db:
        assert len(list_messages(db, conversation_id=conversation_id)) == before


def test_a_click_in_a_conversation_that_offered_nothing_is_not_offered(setup):
    claims, _ = setup

    with pytest.raises(ActionNotOffered) as missed:
        _open_turn(claims, _click("keep_order"))

    assert missed.value.cards == []


def test_retrying_a_stored_click_replays_its_reply_instead_of_saying_it_was_not_offered(setup):
    claims, conversation_id = setup
    _offer(conversation_id, KEEP)
    request = _click("keep_order")
    first = _open_turn(claims, request)
    with SessionLocal() as db:
        finish_turn(db, conversation_id=conversation_id, turn=first, content="Your order stays.", now=NOW)

    retry = _open_turn(claims, request)  # the latest reply no longer holds the button

    assert retry.action is TurnAction.REPLAY and retry.reply == "Your order stays."


def test_the_event_of_a_return_turn_is_saved_with_the_reply_and_only_then(setup):
    from app.db.models import ReturnEvent

    claims, conversation_id = setup
    _offer(conversation_id, KEEP)
    turn = _open_turn(claims, _click("keep_order"))
    event = {
        "tenant_id": claims.tenant_id, "conversation_id": conversation_id, "customer_id": None,
        "identity_level": "anonymous", "user_seq": turn.user_seq, "input_type": "action",
        "action": "keep_order", "outcome": "kept_as_is", "candidates": 0, "model": "m",
        "app_version": "v", "duration_ms": 5,
    }
    with SessionLocal() as db:
        assert db.query(ReturnEvent).count() == 0  # the click alone records nothing
        finish_turn(db, conversation_id=conversation_id, turn=turn, content="Your order stays.", now=NOW, return_event=event)
        saved = db.query(ReturnEvent).one()
        assert (saved.action, saved.outcome, saved.user_seq) == ("keep_order", "kept_as_is", turn.user_seq)
        assert saved.created_at is not None and saved.stage_before is None
