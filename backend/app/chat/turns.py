"""A conversation's stored history, and the rule that only one agent turn runs at a time.

A turn: `begin_turn` saves the user's message and marks the conversation busy, the agent
runs (seconds, so no DB lock is held), `finish_turn` saves the reply and clears the mark.

- A message while a turn runs raises `TurnInProgress`; a mark older than `TURN_STALE_AFTER`
  is ignored, so a crashed process can't wedge a conversation.
- `client_message_id` makes retries safe: an id already stored replays its reply (`REPLAY`)
  instead of running the agent twice, or runs again if it never got one.
- Each run has its own token, and a reply records the seq it answers. A run that outlived
  the stale limit and lost the conversation (even to a retry of its own message) is
  *superseded*: its late `finish_turn` raises `TurnSuperseded` and writes nothing.
- Only plain text is stored (never tool output); the reply is the final one, post-guardrail.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from app.db.models import Conversation, Message

DEFAULT_HISTORY_LIMIT = 20
TURN_STALE_AFTER = timedelta(minutes=2)


class TurnAction(StrEnum):
    RUN = "run"
    REPLAY = "replay"


class TurnInProgress(Exception):
    pass


class MessageIdReused(Exception):
    """A stored `client_message_id` came back with different text."""


class TurnSuperseded(Exception):
    """The turn lost the conversation to a newer one and must not write its reply."""


@dataclass(frozen=True)
class TurnStart:
    action: TurnAction
    user_seq: int = 0  # seq of the user's message
    turn_id: uuid.UUID | None = None  # this run's token: pass the TurnStart to finish/abandon
    user_text: str = ""
    history: list[Message] = field(default_factory=list)  # oldest first, excludes the new message
    reply: str | None = None


def _lock(db: Session, conversation_id: uuid.UUID) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter_by(id=conversation_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if conversation is None:
        db.commit()  # end the transaction instead of leaving it open
        raise LookupError(f"no conversation {conversation_id}")
    return conversation


def _busy(conversation: Conversation, now: datetime) -> bool:
    started = conversation.turn_started_at
    return started is not None and now - started < TURN_STALE_AFTER


def _history_before(db: Session, conversation_id: uuid.UUID, seq: int, limit: int) -> list[Message]:
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.seq < seq)
        .order_by(Message.seq.desc())
        .limit(limit)
        .all()
    )
    return rows[::-1]


def _append(
    db: Session,
    conversation: Conversation,
    role: str,
    content: str,
    now: datetime,
    client_message_id: uuid.UUID | None = None,
    reply_to_seq: int | None = None,
) -> Message:
    conversation.last_seq += 1
    conversation.last_activity_at = now
    message = Message(
        conversation_id=conversation.id,
        seq=conversation.last_seq,
        role=role,
        content=content,
        client_message_id=client_message_id,
        reply_to_seq=reply_to_seq,
        created_at=now,
    )
    db.add(message)
    return message


def begin_turn(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    client_message_id: uuid.UUID,
    content: str,
    now: datetime,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
) -> TurnStart:
    conversation = _lock(db, conversation_id)
    turn_id = uuid.uuid4()
    existing = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, client_message_id=client_message_id)
        .one_or_none()
    )

    if existing is not None:
        if existing.content != content:
            db.commit()
            raise MessageIdReused
        reply = (
            db.query(Message)
            .filter_by(conversation_id=conversation_id, reply_to_seq=existing.seq)
            .one_or_none()
        )
        if reply is not None:
            db.commit()  # nothing changed; ends the transaction and frees the lock
            return TurnStart(TurnAction.REPLAY, reply=reply.content)
        if _busy(conversation, now):
            db.commit()
            raise TurnInProgress
        conversation.turn_started_at, conversation.turn_id = now, turn_id
        user_text, history_seq = existing.content, existing.seq
    else:
        if _busy(conversation, now):
            db.commit()
            raise TurnInProgress
        message = _append(db, conversation, "user", content, now, client_message_id)
        db.flush()
        conversation.turn_started_at, conversation.turn_id = now, turn_id
        user_text, history_seq = content, message.seq

    history = _history_before(db, conversation_id, history_seq, history_limit)
    db.commit()
    return TurnStart(
        TurnAction.RUN, user_seq=history_seq, turn_id=turn_id, user_text=user_text, history=history
    )


def finish_turn(
    db: Session, *, conversation_id: uuid.UUID, turn: TurnStart, content: str, now: datetime
) -> None:
    conversation = _lock(db, conversation_id)
    if conversation.turn_id != turn.turn_id:
        db.commit()
        raise TurnSuperseded
    _append(db, conversation, "assistant", content, now, reply_to_seq=turn.user_seq)
    conversation.turn_started_at = conversation.turn_id = None
    db.commit()


def abandon_turn(db: Session, *, conversation_id: uuid.UUID, turn: TurnStart) -> None:
    """The turn failed: free the conversation for a retry, unless a newer run took over."""
    conversation = _lock(db, conversation_id)
    if conversation.turn_id == turn.turn_id:
        conversation.turn_started_at = conversation.turn_id = None
    db.commit()


def list_messages(db: Session, *, conversation_id: uuid.UUID) -> list[Message]:
    return db.query(Message).filter_by(conversation_id=conversation_id).order_by(Message.seq).all()
