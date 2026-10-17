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
    TurnAction,
    TurnInProgress,
    TurnSuperseded,
    abandon_turn,
    begin_turn,
    finish_turn,
    list_messages,
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
