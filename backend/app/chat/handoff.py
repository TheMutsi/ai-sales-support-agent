"""What a person from the back office does to a conversation that was escalated to them.

`claim` (a person joins), `reply` (they speak) and `close` (the assistant takes over again) change
the conversation's handoff state and add the messages the visitor reads, under the conversation's
row lock like every other write to it (`app.chat.turns`). An offline escalation has no chat to
join: `resolve` only marks it done, with a note of what was done.
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.chat.turns import HandoffStatus, MessageKind, _append, _lock
from app.db.models import Conversation, Message


class HandoffError(Exception):
    """The conversation is not in the state this needs. `code` is what the API reports."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _resolve(conversation: Conversation, *, agent_name: str, now: datetime, notes: str | None) -> None:
    if conversation.escalation_status == "open":
        conversation.escalation_status = "resolved"
        conversation.escalation_resolved_at = now
        conversation.escalation_resolved_by = agent_name
        conversation.escalation_notes = notes


def claim(db: Session, *, conversation_id: uuid.UUID, agent_name: str, now: datetime) -> None:
    conversation = _lock(db, conversation_id)
    if conversation.handoff_status != HandoffStatus.WAITING:
        db.commit()
        raise HandoffError("not_waiting")
    conversation.handoff_status = HandoffStatus.ACTIVE
    conversation.handoff_agent_name = agent_name
    _append(db, conversation, "system", f"{agent_name} joined the chat.", now, kind=MessageKind.SYSTEM)
    db.commit()


def reply(
    db: Session, *, conversation_id: uuid.UUID, agent_name: str, text: str, now: datetime
) -> Message:
    conversation = _lock(db, conversation_id)
    if conversation.handoff_status != HandoffStatus.ACTIVE:
        db.commit()
        raise HandoffError("not_active")
    message = _append(db, conversation, "human", text, now)
    message.author_name = agent_name
    db.commit()
    return message


def close(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    agent_name: str,
    now: datetime,
    notes: str | None = None,
) -> None:
    """Gives the conversation back to the assistant and resolves the escalation that started it."""
    conversation = _lock(db, conversation_id)
    if conversation.handoff_status == HandoffStatus.NONE:
        db.commit()
        raise HandoffError("not_in_handoff")
    _resolve(conversation, agent_name=agent_name, now=now, notes=notes)
    # Closing while still waiting: nobody joined, so nobody "left".
    notice = (
        f"{agent_name} left the chat. The assistant is back."
        if conversation.handoff_status == HandoffStatus.ACTIVE
        else "The assistant is back."
    )
    conversation.handoff_status = HandoffStatus.NONE
    conversation.handoff_agent_name = None
    _append(db, conversation, "system", notice, now, kind=MessageKind.SYSTEM)
    db.commit()


def resolve(
    db: Session, *, conversation_id: uuid.UUID, agent_name: str, now: datetime, notes: str | None = None
) -> None:
    """Marks an offline escalation done. A live one is closed with `close` instead, which also
    hands the chat back to the assistant."""
    conversation = _lock(db, conversation_id)
    if conversation.escalation_status != "open" or conversation.handoff_status != HandoffStatus.NONE:
        db.commit()
        raise HandoffError("not_open")
    _resolve(conversation, agent_name=agent_name, now=now, notes=notes)
    db.commit()
