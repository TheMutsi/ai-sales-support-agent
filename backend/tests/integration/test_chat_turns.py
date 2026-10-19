"""A conversation's stored history and the one-turn-at-a-time rule: the same
`client_message_id` replays its reply, and another message while a turn runs is refused."""

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.conversations import create_anonymous
from app.auth.credentials import generate_api_key
from app.chat.turns import (
    MessageIdReused,
    MessageKind,
    TurnAction,
    TurnInProgress,
    TurnSuperseded,
    abandon_turn,
    begin_turn,
    finish_turn,
    list_messages,
    pending_message,
)
from app.db.models import Conversation, Tenant
from app.db.session import SessionLocal

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tenant_wipe):
    with SessionLocal() as session:
        yield session


@pytest.fixture
def conversation(db) -> Conversation:
    tenant = Tenant(name="Shop", api_key=generate_api_key())
    db.add(tenant)
    db.flush()
    return create_anonymous(db, tenant_id=tenant.id, now=NOW)


def _begin(db, conversation, text="hi", message_id=None, now=NOW, **kwargs):
    return begin_turn(
        db,
        conversation_id=conversation.id,
        client_message_id=message_id or uuid.uuid4(),
        content=text,
        now=now,
        **kwargs,
    )


def _finish(db, conversation, turn, reply, now=NOW):
    finish_turn(db, conversation_id=conversation.id, turn=turn, content=reply, now=now)


def _ask_for_identity(db, conversation, turn, now=NOW):
    finish_turn(
        db,
        conversation_id=conversation.id,
        turn=turn,
        content="I need to verify it is you.",
        now=now,
        kind=MessageKind.IDENTITY_REQUEST,
    )


def _complete(db, conversation, user_text, reply, now=NOW):
    _finish(db, conversation, _begin(db, conversation, user_text, now=now), reply, now)


def test_the_first_turn_runs_with_no_history_and_stores_the_user_message(db, conversation):
    turn = _begin(db, conversation, "hello")

    assert turn.action is TurnAction.RUN
    assert turn.history == [] and turn.user_text == "hello"
    stored = list_messages(db, conversation_id=conversation.id)
    assert [(m.seq, m.role, m.content) for m in stored] == [(1, "user", "hello")]


def test_the_reply_is_stored_and_the_next_turn_sees_the_whole_exchange(db, conversation):
    _complete(db, conversation, "hello", "Hi there")

    turn = _begin(db, conversation, "and pricing?")

    assert [(m.role, m.content) for m in turn.history] == [("user", "hello"), ("assistant", "Hi there")]
    assert [m.seq for m in list_messages(db, conversation_id=conversation.id)] == [1, 2, 3]


def test_only_the_most_recent_messages_are_given_to_the_model_in_order(db, conversation):
    for i in range(5):
        _complete(db, conversation, f"q{i}", f"a{i}")

    turn = _begin(db, conversation, "last", history_limit=4)

    assert [m.content for m in turn.history] == ["q3", "a3", "q4", "a4"]


def test_sending_the_same_message_again_replays_the_reply_without_a_new_turn(db, conversation):
    message_id = uuid.uuid4()
    _finish(db, conversation, _begin(db, conversation, "hello", message_id=message_id), "Hi there")

    again = _begin(db, conversation, "hello", message_id=message_id)

    assert again.action is TurnAction.REPLAY and again.reply == "Hi there"
    assert len(list_messages(db, conversation_id=conversation.id)) == 2


def test_a_message_id_cannot_be_reused_for_different_text(db, conversation):
    """Replaying the stored answer for other text would answer a question that was never asked."""
    message_id = uuid.uuid4()
    _finish(db, conversation, _begin(db, conversation, "hello", message_id=message_id), "Hi there")

    with pytest.raises(MessageIdReused):
        _begin(db, conversation, "something else", message_id=message_id)

    assert len(list_messages(db, conversation_id=conversation.id)) == 2


@pytest.mark.parametrize("same_message", [False, True])
def test_a_message_while_a_turn_is_running_is_refused(db, conversation, same_message):
    message_id = uuid.uuid4()
    _begin(db, conversation, "first", message_id=message_id)

    with pytest.raises(TurnInProgress):
        _begin(db, conversation, "first", message_id=message_id if same_message else None)


def test_a_turn_that_never_finished_stops_blocking_after_a_while(db, conversation):
    _begin(db, conversation, "first")
    later = NOW + timedelta(minutes=3)

    assert _begin(db, conversation, "second", now=later).action is TurnAction.RUN


def test_abandoning_a_turn_lets_the_same_message_be_retried_without_duplicating_it(db, conversation):
    message_id = uuid.uuid4()
    turn = _begin(db, conversation, "hello", message_id=message_id)
    abandon_turn(db, conversation_id=conversation.id, turn=turn)

    retry = _begin(db, conversation, "hello", message_id=message_id)

    assert retry.action is TurnAction.RUN and retry.history == []
    assert retry.user_text == "hello"
    assert len(list_messages(db, conversation_id=conversation.id)) == 1


def test_a_second_request_waits_for_the_lock_and_then_finds_the_conversation_busy(db, conversation):
    outcome = {}

    def other_tab():
        with SessionLocal() as other:
            try:
                begin_turn(
                    other, conversation_id=conversation.id, client_message_id=uuid.uuid4(),
                    content="from tab two", now=NOW,
                )
                outcome["result"] = "ran"
            except TurnInProgress:
                outcome["result"] = "refused"

    with SessionLocal() as holder:  # tab one is mid-way through starting its turn
        row = holder.query(Conversation).filter_by(id=conversation.id).with_for_update().one()
        thread = threading.Thread(target=other_tab)
        thread.start()
        time.sleep(0.3)
        assert thread.is_alive(), "the second request should wait for the lock"
        row.turn_started_at = NOW
        holder.commit()
    thread.join(timeout=5)

    assert outcome["result"] == "refused"


def _stale_then_new_turn(db, conversation, retry_same_message=False):
    a_id = uuid.uuid4()
    a = _begin(db, conversation, "slow question", message_id=a_id)
    later = NOW + timedelta(minutes=3)
    b = _begin(db, conversation, "slow question" if retry_same_message else "new question",
               message_id=a_id if retry_same_message else None, now=later)
    return a_id, a, b, later


@pytest.mark.parametrize("retry_same_message", [False, True])
@pytest.mark.parametrize("how", ["finishes", "fails"])
def test_a_stale_turn_ending_late_cannot_free_or_write_into_the_new_one(
    db, conversation, how, retry_same_message
):
    _, a, b, later = _stale_then_new_turn(db, conversation, retry_same_message)

    if how == "finishes":
        with pytest.raises(TurnSuperseded):
            _finish(db, conversation, a, "late answer to A", now=later)
    else:
        abandon_turn(db, conversation_id=conversation.id, turn=a)

    with pytest.raises(TurnInProgress):  # the new turn still owns the conversation
        _begin(db, conversation, "third", now=later)
    _finish(db, conversation, b, "answer to B", now=later)  # and can still finish
    stored = [m.content for m in list_messages(db, conversation_id=conversation.id)]
    assert "answer to B" in stored and "late answer to A" not in stored


def test_retrying_an_old_message_never_replays_someone_elses_reply(db, conversation):
    a_id, _, b, later = _stale_then_new_turn(db, conversation)
    _finish(db, conversation, b, "answer to B", now=later)

    retry = _begin(db, conversation, "slow question", message_id=a_id, now=later)
    assert retry.action is TurnAction.RUN and retry.user_text == "slow question"
    _finish(db, conversation, retry, "answer to A", now=later)

    again = _begin(db, conversation, "slow question", message_id=a_id, now=later)
    assert again.action is TurnAction.REPLAY and again.reply == "answer to A"


def test_a_message_defaults_to_text(db, conversation):
    _complete(db, conversation, "hello", "Hi")

    assert [m.kind for m in list_messages(db, conversation_id=conversation.id)] == ["text", "text"]


def test_an_identity_request_is_stored_with_its_kind(db, conversation):
    _ask_for_identity(db, conversation, _begin(db, conversation, "my invoice?"))

    stored = list_messages(db, conversation_id=conversation.id)

    assert [(m.role, m.kind) for m in stored] == [("user", "text"), ("assistant", "identity_request")]


def test_the_model_never_sees_an_identity_request_in_the_history(db, conversation):
    """It is a form the widget shows, not something the assistant said about the product."""
    _ask_for_identity(db, conversation, _begin(db, conversation, "my invoice?"))

    turn = _begin(db, conversation, "never mind, what are your plans?")

    assert [(m.role, m.content) for m in turn.history] == [("user", "my invoice?")]


def test_retrying_the_message_after_an_identity_request_runs_it_again_and_can_be_answered(
    db, conversation
):
    """This is how a turn resumes once the visitor has identified: same message id, no reply
    yet. The identity request must not count as its reply, or it would be replayed forever."""
    message_id = uuid.uuid4()
    _ask_for_identity(db, conversation, _begin(db, conversation, "my invoice?", message_id=message_id))

    again = _begin(db, conversation, "my invoice?", message_id=message_id)

    assert again.action is TurnAction.RUN and again.user_text == "my invoice?"
    _finish(db, conversation, again, "Your next invoice is on the 3rd.")
    assert _begin(db, conversation, "my invoice?", message_id=message_id).action is TurnAction.REPLAY


def test_the_pending_message_is_the_one_the_identity_request_was_about(db, conversation):
    message_id = uuid.uuid4()
    _ask_for_identity(db, conversation, _begin(db, conversation, "my invoice?", message_id=message_id))

    pending = pending_message(db, conversation_id=conversation.id)

    assert (pending.content, pending.client_message_id) == ("my invoice?", message_id)


def test_nothing_is_pending_in_a_new_conversation_or_after_a_normal_answer(db, conversation):
    assert pending_message(db, conversation_id=conversation.id) is None

    _complete(db, conversation, "hello", "Hi")

    assert pending_message(db, conversation_id=conversation.id) is None


def test_nothing_is_pending_once_the_visitor_moved_on(db, conversation):
    """The form is only the last word of the conversation until something else is said."""
    _ask_for_identity(db, conversation, _begin(db, conversation, "my invoice?"))
    _complete(db, conversation, "never mind, what are your plans?", "Three plans.")

    assert pending_message(db, conversation_id=conversation.id) is None


def test_the_latest_unanswered_question_is_the_pending_one(db, conversation):
    _complete(db, conversation, "hello", "Hi")
    first_form = _begin(db, conversation, "my invoice?")
    _ask_for_identity(db, conversation, first_form)
    _ask_for_identity(db, conversation, _begin(db, conversation, "and my refund?"))

    assert pending_message(db, conversation_id=conversation.id).content == "and my refund?"


def test_a_pending_return_is_kept_between_turns_and_cleared_when_asked(db, conversation):
    from app.schemas.orders import PendingReturn, ReturnStage

    pending = PendingReturn(order_id="A" * 20, stage=ReturnStage.OFFER)
    first = _begin(db, conversation, "I want to reject my order")
    finish_turn(
        db, conversation_id=conversation.id, turn=first, content="Here is an offer", now=NOW,
        pending_return=pending,
    )

    second = _begin(db, conversation, "tell me about the plans", now=NOW + timedelta(seconds=5))
    assert second.pending_return == pending  # the next turn starts from it
    finish_turn(db, conversation_id=conversation.id, turn=second, content="Plans...", now=NOW)  # not touched
    third = _begin(db, conversation, "the credits", now=NOW + timedelta(seconds=10))
    assert third.pending_return == pending

    finish_turn(
        db, conversation_id=conversation.id, turn=third, content="Done", now=NOW, pending_return=None
    )
    assert _begin(db, conversation, "thanks", now=NOW + timedelta(seconds=15)).pending_return is None


def test_a_pending_return_is_dropped_when_it_is_not_answered_in_time(db, conversation):
    from app.chat.turns import PENDING_RETURN_TTL
    from app.schemas.orders import PendingReturn, ReturnStage

    pending = PendingReturn(order_id="A" * 20, stage=ReturnStage.CONFIRM)
    first = _begin(db, conversation, "cancel my order")
    finish_turn(
        db, conversation_id=conversation.id, turn=first, content="Confirm?", now=NOW, pending_return=pending
    )

    soon = _begin(db, conversation, "yes", now=NOW + PENDING_RETURN_TTL)
    finish_turn(db, conversation_id=conversation.id, turn=soon, content="ok", now=NOW + PENDING_RETURN_TTL)
    late = _begin(db, conversation, "yes", now=NOW + PENDING_RETURN_TTL + timedelta(seconds=1))

    assert soon.pending_return == pending  # still within the time
    assert late.pending_return is None  # a later "yes" cannot complete it


def test_carrying_a_pending_return_along_does_not_restart_its_time(db, conversation):
    from app.chat.turns import PENDING_RETURN_TTL
    from app.schemas.orders import PendingReturn, ReturnStage

    pending = PendingReturn(order_id="A" * 20, stage=ReturnStage.OFFER)
    first = _begin(db, conversation, "reject my order")
    finish_turn(db, conversation_id=conversation.id, turn=first, content="Offer", now=NOW, pending_return=pending)
    other = NOW + PENDING_RETURN_TTL / 2
    second = _begin(db, conversation, "what plans are there?", now=other)
    finish_turn(db, conversation_id=conversation.id, turn=second, content="Plans", now=other, pending_return=pending)

    late = _begin(db, conversation, "yes", now=NOW + PENDING_RETURN_TTL + timedelta(seconds=1))

    assert late.pending_return is None


def test_a_return_offered_again_after_it_lapsed_gets_a_fresh_time(db, conversation):
    from app.chat.turns import PENDING_RETURN_TTL
    from app.schemas.orders import PendingReturn, ReturnStage

    pending = PendingReturn(order_id="A" * 20, stage=ReturnStage.OFFER)
    first = _begin(db, conversation, "reject my order")
    finish_turn(db, conversation_id=conversation.id, turn=first, content="Offer", now=NOW, pending_return=pending)

    later = NOW + PENDING_RETURN_TTL + timedelta(seconds=1)
    again = _begin(db, conversation, "reject my order again", now=later)
    assert again.pending_return is None  # the first one lapsed
    finish_turn(db, conversation_id=conversation.id, turn=again, content="Offer", now=later, pending_return=pending)

    answer = _begin(db, conversation, "the credits", now=later + timedelta(minutes=1))

    assert answer.pending_return == pending


def test_the_cards_of_a_reply_are_stored_with_it_and_a_plain_reply_has_none(db, conversation):
    from app.schemas.cards import ActionCard
    from app.schemas.chat import StoredMessage

    card = ActionCard(id="offer-refund", title="$14.00 back", message="I'll take the refund")
    first = _begin(db, conversation, "reject my order")
    finish_turn(db, conversation_id=conversation.id, turn=first, content="Here are your options", now=NOW, cards=[card])
    second = _begin(db, conversation, "thanks", now=NOW + timedelta(seconds=5))
    finish_turn(db, conversation_id=conversation.id, turn=second, content="You're welcome", now=NOW)

    stored = [StoredMessage.model_validate(m, from_attributes=True) for m in list_messages(db, conversation_id=conversation.id)]

    assistant = [m for m in stored if m.role == "assistant"]
    assert [c.id for c in assistant[0].cards] == ["offer-refund"] and assistant[1].cards == []


def test_a_retried_message_replays_its_reply_with_its_cards(db, conversation):
    from app.schemas.cards import ActionCard

    card = ActionCard(id="confirm-yes", title="Yes, cancel it", message="Yes, cancel it")
    message_id = uuid.uuid4()
    first = _begin(db, conversation, "cancel my order", message_id=message_id)
    finish_turn(db, conversation_id=conversation.id, turn=first, content="Sure?", now=NOW, cards=[card])

    again = _begin(db, conversation, "cancel my order", message_id=message_id, now=NOW + timedelta(seconds=3))

    assert again.action is TurnAction.REPLAY and again.reply == "Sure?"
    assert [c["id"] for c in again.reply_cards] == ["confirm-yes"]
