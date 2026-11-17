import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from app.business.escalation import EscalationRoute
from app.db.models import Conversation, Message, ReturnEvent
from app.schemas.cards import Card, CardAction
from app.schemas.orders import PendingReturn, ReturnStage
from app.schemas.tools import EscalationReceipt

DEFAULT_HISTORY_LIMIT = 20
TURN_STALE_AFTER = timedelta(minutes=2)


class MessageKind(StrEnum):
    TEXT = "text"
    IDENTITY_REQUEST = "identity_request"
    SYSTEM = "system"


class HandoffStatus(StrEnum):
    NONE = "none"
    WAITING = "waiting"
    ACTIVE = "active"


class TurnAction(StrEnum):
    RUN = "run"
    REPLAY = "replay"
    HANDOFF = "handoff"


class TurnInProgress(Exception):
    pass


class MessageIdReused(Exception):
    pass


class TurnSuperseded(Exception):
    pass


PENDING_RETURN_TTL = timedelta(minutes=15)


class Keep:
    pass


KEEP = Keep()


@dataclass(frozen=True)
class TurnStart:
    action: TurnAction
    user_seq: int = 0
    turn_id: uuid.UUID | None = None
    user_text: str = ""
    history: list[Message] = field(default_factory=list)
    reply: str | None = None
    reply_cards: list | None = None
    handoff: HandoffStatus = HandoffStatus.NONE
    pending_return: PendingReturn | None = None
    click: CardAction | None = None
    click_order_id: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    open_escalation: EscalationReceipt | None = None


ESCALATION_NOTICE = (
    "You asked to speak with a person. An agent will join this chat when one is free; "
    "you can keep writing here."
)


def _lock(db: Session, conversation_id: uuid.UUID) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter_by(id=conversation_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if conversation is None:
        db.commit()
        raise LookupError(f"no conversation {conversation_id}")
    return conversation


def _busy(conversation: Conversation, now: datetime) -> bool:
    started = conversation.turn_started_at
    return started is not None and now - started < TURN_STALE_AFTER


def _history_before(db: Session, conversation_id: uuid.UUID, seq: int, limit: int) -> list[Message]:
    rows = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.seq < seq,
            Message.kind == MessageKind.TEXT,
            Message.role.in_(("user", "assistant")),
        )
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
    kind: MessageKind = MessageKind.TEXT,
    cards: list[Card] | None = None,
) -> Message:
    conversation.last_seq += 1
    conversation.last_activity_at = now
    message = Message(
        conversation_id=conversation.id,
        seq=conversation.last_seq,
        role=role,
        kind=kind.value,
        content=content,
        client_message_id=client_message_id,
        reply_to_seq=reply_to_seq,
        created_at=now,
        cards=[card.model_dump(mode="json") for card in cards] if cards else None,
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
            db.commit()
            return TurnStart(TurnAction.REPLAY, reply=reply.content, reply_cards=reply.cards)
        if conversation.handoff_status != HandoffStatus.NONE:
            db.commit()
            return TurnStart(TurnAction.HANDOFF, handoff=HandoffStatus(conversation.handoff_status))
        if _busy(conversation, now):
            db.commit()
            raise TurnInProgress
        conversation.turn_started_at, conversation.turn_id = now, turn_id
        user_text, history_seq = existing.content, existing.seq
    elif conversation.handoff_status != HandoffStatus.NONE:
        _append(db, conversation, "user", content, now, client_message_id)
        db.commit()
        return TurnStart(TurnAction.HANDOFF, handoff=HandoffStatus(conversation.handoff_status))
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
    pending = None
    if (
        conversation.pending_return_order_id
        and conversation.pending_return_stage
        and conversation.pending_return_at is not None
        and now - conversation.pending_return_at <= PENDING_RETURN_TTL
    ):
        pending = PendingReturn(
            order_id=conversation.pending_return_order_id,
            stage=ReturnStage(conversation.pending_return_stage),
        )
    return TurnStart(
        TurnAction.RUN,
        user_seq=history_seq,
        turn_id=turn_id,
        user_text=user_text,
        history=history,
        pending_return=pending,
        properties=dict(conversation.properties),
        tags=list(conversation.tags),
        open_escalation=_open_escalation(conversation),
    )


def _open_escalation(conversation: Conversation) -> EscalationReceipt | None:
    if conversation.escalation_status != "open":
        return None
    return EscalationReceipt(
        reference=conversation.escalation_reference,
        route=conversation.escalation_route,
        reason=conversation.escalation_reason,
        category=conversation.escalation_category,
    )


def finish_turn(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    turn: TurnStart,
    content: str,
    now: datetime,
    kind: MessageKind = MessageKind.TEXT,
    escalation: EscalationReceipt | None = None,
    pending_return: PendingReturn | None | Keep = KEEP,
    cards: list[Card] | None = None,
    return_event: dict | None = None,
) -> None:
    conversation = _lock(db, conversation_id)
    if conversation.turn_id != turn.turn_id:
        db.commit()
        raise TurnSuperseded
    reply_to = turn.user_seq if kind is MessageKind.TEXT else None
    _append(db, conversation, "assistant", content, now, reply_to_seq=reply_to, kind=kind, cards=cards)
    if return_event is not None:
        db.add(ReturnEvent(**return_event))
    if escalation is not None:
        _record_escalation(db, conversation, escalation, now)
    if not isinstance(pending_return, Keep):
        order_id = pending_return.order_id if pending_return else None
        stage = pending_return.stage.value if pending_return else None
        if pending_return != turn.pending_return:
            conversation.pending_return_at = now if pending_return else None
        conversation.pending_return_order_id, conversation.pending_return_stage = order_id, stage
    conversation.turn_started_at = conversation.turn_id = None
    db.commit()


def _record_escalation(
    db: Session, conversation: Conversation, escalation: EscalationReceipt, now: datetime
) -> None:
    if conversation.escalation_status == "open":
        upgraded = (
            escalation.reference == conversation.escalation_reference
            and escalation.route is EscalationRoute.LIVE
            and conversation.escalation_route != EscalationRoute.LIVE
        )
        if not upgraded:
            return
        conversation.escalation_route, conversation.escalation_reason = escalation.route, escalation.reason
    else:
        if conversation.escalation_reference is not None:
            conversation.escalation_history = [*conversation.escalation_history, _past_escalation(conversation)]
        conversation.escalation_reference = escalation.reference
        conversation.escalation_route = escalation.route
        conversation.escalation_reason = escalation.reason
        conversation.escalation_category = escalation.category
        conversation.escalation_status = "open"
        conversation.escalated_at = now
        conversation.escalation_resolved_at = conversation.escalation_resolved_by = None
        conversation.escalation_notes = None
    if escalation.route is EscalationRoute.LIVE and conversation.handoff_status == HandoffStatus.NONE:
        conversation.handoff_status = HandoffStatus.WAITING
        conversation.handoff_requested_at = now
        _append(db, conversation, "system", ESCALATION_NOTICE, now, kind=MessageKind.SYSTEM)


def _past_escalation(conversation: Conversation) -> dict:
    def iso(moment: datetime | None) -> str | None:
        return moment.isoformat() if moment else None

    return {
        "reference": conversation.escalation_reference,
        "route": conversation.escalation_route,
        "reason": conversation.escalation_reason,
        "category": conversation.escalation_category,
        "escalated_at": iso(conversation.escalated_at),
        "resolved_at": iso(conversation.escalation_resolved_at),
        "resolved_by": conversation.escalation_resolved_by,
        "notes": conversation.escalation_notes,
    }


def abandon_turn(db: Session, *, conversation_id: uuid.UUID, turn: TurnStart) -> None:
    conversation = _lock(db, conversation_id)
    if conversation.turn_id == turn.turn_id:
        conversation.turn_started_at = conversation.turn_id = None
    db.commit()


def list_messages(db: Session, *, conversation_id: uuid.UUID) -> list[Message]:
    return db.query(Message).filter_by(conversation_id=conversation_id).order_by(Message.seq).all()


def pending_message(db: Session, *, conversation_id: uuid.UUID) -> Message | None:
    last = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id)
        .order_by(Message.seq.desc())
        .first()
    )
    if last is None or last.kind != MessageKind.IDENTITY_REQUEST:
        return None
    return (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.role == "user",
            Message.seq < last.seq,
        )
        .order_by(Message.seq.desc())
        .first()
    )
