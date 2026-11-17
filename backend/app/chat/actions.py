import uuid

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.chat.turns import MessageKind
from app.db.models import Message
from app.schemas.cards import ActionCard, Card, CardAction

_CARDS = TypeAdapter(list[Card])


def latest_cards(db: Session, conversation_id: uuid.UUID) -> list[Card]:
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
