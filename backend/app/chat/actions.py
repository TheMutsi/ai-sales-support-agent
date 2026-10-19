"""Checking that a clicked button was really offered.

A click carries only `action` (and `order_id`). The cards that were shown are stored with the
reply, so the answer to "was this offered?" is in the conversation itself: the latest assistant
message must hold a card with that same action. That covers a button from an older question
(another tab), a repeated click and an action made up by hand. The text the click says in the
conversation is taken from that card, never from the client.

This only says whether it was offered. Whether it fits the step the customer is in is decided by
the step itself (see `order_return`).
"""

import uuid

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.chat.turns import MessageKind
from app.db.models import Message
from app.schemas.cards import ActionCard, Card, CardAction

_CARDS = TypeAdapter(list[Card])


def latest_cards(db: Session, conversation_id: uuid.UUID) -> list[Card]:
    """The cards of the latest assistant reply, as they were stored."""
    last = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, role="assistant", kind=MessageKind.TEXT.value)
        .order_by(Message.seq.desc())
        .first()
    )
    if last is None or not last.cards:
        return []
    return _CARDS.validate_python(last.cards)


def offered_card(cards: list[Card], action: CardAction, order_id: str | None) -> ActionCard | None:
    for card in cards:
        if isinstance(card, ActionCard) and card.action == action and card.order_id == order_id:
            return card
    return None
