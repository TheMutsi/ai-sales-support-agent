"""What a person from the back office does to a conversation that was escalated to them.

`claim` (a person joins), `reply` (they speak) and `close` (the assistant takes over again) change
the conversation's handoff state and add the messages the visitor reads, under the conversation's
row lock like every other write to it (`app.chat.turns`).
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.chat.turns import HandoffStatus, MessageKind, _append, _lock
from app.db.models import Message, Ticket


class HandoffError(Exception):
    """The conversation is not in the state this needs. `code` is what the API reports."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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
    """Gives the conversation back to the assistant and resolves the ticket that started it."""
    conversation = _lock(db, conversation_id)
    if conversation.handoff_status == HandoffStatus.NONE:
        db.commit()
        raise HandoffError("not_in_handoff")
    ticket = db.get(Ticket, conversation.handoff_ticket_id) if conversation.handoff_ticket_id else None
    if ticket is not None:
        ticket.status, ticket.resolved_at, ticket.resolution_notes = "resolved", now, notes
    conversation.handoff_status = HandoffStatus.NONE
    conversation.handoff_agent_name = None
    _append(
        db, conversation, "system", f"{agent_name} left the chat. The assistant is back.", now,
        kind=MessageKind.SYSTEM,
    )
    db.commit()
