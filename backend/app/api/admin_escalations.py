import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, case, cast, exists, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.admin.permissions import ROLE_PERMISSIONS, Permission
from app.admin.session import AdminSession
from app.api.admin_conversations import CustomerView, MessageView, customer_view
from app.api.admin_deps import error, require_tenant_permission
from app.chat import handoff, presence
from app.chat.handoff import HandoffError
from app.chat.turns import HandoffStatus
from app.db.models import Conversation, Customer, Message
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

_PREVIEW_CHARS = 120
_READ = require_tenant_permission(Permission.ESCALATIONS_READ)
_ACT = require_tenant_permission(Permission.ESCALATIONS_REPLY)


class EscalationItem(BaseModel):
    id: uuid.UUID
    reference: str
    route: Literal["live", "offline"]
    reason: str | None
    category: str | None
    status: Literal["open", "resolved"]
    handoff_status: str
    agent_name: str | None
    escalated_at: datetime | None
    resolved_at: datetime | None
    resolved_by: str | None
    notes: str | None
    customer: CustomerView | None
    tags: list[str]
    properties: dict[str, str]
    last_message: str | None


class ReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CloseRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


def _conversation_of(db: Session, tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant_id:
        raise error(404, "conversation_not_found")


def _act(db: Session, tenant_id: uuid.UUID, conversation_id: uuid.UUID, do):
    _conversation_of(db, tenant_id, conversation_id)
    try:
        return do()
    except HandoffError as problem:
        raise error(409, problem.code) from None


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _property_filter(raw: str):
    key, separator, value = raw.partition(":")
    if not separator or not key.strip():
        raise error(422, "bad_property_filter")
    return cast(Conversation.properties, JSONB).contains({key.strip(): value.strip()})


@router.get("/tenants/{tenant_id}/escalations", response_model=list[EscalationItem])
def list_escalations(
    tenant_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_READ)],
    db: Annotated[Session, Depends(get_db)],
    status: Literal["open", "resolved", "all"] = "open",
    route: Literal["live", "offline"] | None = None,
    category: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    tag: Annotated[list[str] | None, Query(max_length=10)] = None,
    property: Annotated[list[str] | None, Query(max_length=10)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[EscalationItem]:
    if ROLE_PERMISSIONS[session.role] & {Permission.ESCALATIONS_REPLY}:
        presence.touch(db, tenant_id=tenant_id, agent_name=session.name, now=datetime.now(UTC))

    last_message = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id, Message.role == "user")
        .order_by(Message.seq.desc())
        .limit(1)
        .scalar_subquery()
    )
    query = (
        select(Conversation, Customer, last_message)
        .outerjoin(Customer, Customer.id == Conversation.customer_id)
        .where(Conversation.tenant_id == tenant_id, Conversation.escalation_status.is_not(None))
    )
    if status != "all":
        query = query.where(Conversation.escalation_status == status)
    if route:
        query = query.where(Conversation.escalation_route == route)
    if category:
        query = query.where(Conversation.escalation_category == category)
    if since:
        query = query.where(Conversation.escalated_at >= since)
    if until:
        query = query.where(Conversation.escalated_at < until)
    for one_tag in tag or []:
        query = query.where(cast(Conversation.tags, JSONB).contains([one_tag]))
    for one_property in property or []:
        query = query.where(_property_filter(one_property))
    if q and q.strip():
        pattern = _like(q.strip())
        said = exists().where(
            Message.conversation_id == Conversation.id,
            Message.role == "user",
            Message.content.ilike(pattern, escape="\\"),
        )
        query = query.where(
            or_(
                Conversation.escalation_reference.ilike(pattern, escape="\\"),
                cast(Conversation.escalation_history, String).ilike(pattern, escape="\\"),
                Customer.name.ilike(pattern, escape="\\"),
                Customer.email.ilike(pattern, escape="\\"),
                said,
            )
        )
    waiting_first = case(
        (Conversation.escalation_status == "resolved", 3),
        (Conversation.handoff_status == HandoffStatus.WAITING, 0),
        (Conversation.handoff_status == HandoffStatus.ACTIVE, 1),
        else_=2,
    )
    resolved_newest = case((Conversation.escalation_status == "resolved", Conversation.escalated_at), else_=None)
    rows = db.execute(
        query.order_by(waiting_first, resolved_newest.desc().nulls_last(), Conversation.escalated_at)
        .limit(limit)
        .offset(offset)
    )
    return [
        EscalationItem(
            id=conversation.id,
            reference=conversation.escalation_reference,
            route=conversation.escalation_route,
            reason=conversation.escalation_reason,
            category=conversation.escalation_category,
            status=conversation.escalation_status,
            handoff_status=conversation.handoff_status,
            agent_name=conversation.handoff_agent_name,
            escalated_at=conversation.escalated_at,
            resolved_at=conversation.escalation_resolved_at,
            resolved_by=conversation.escalation_resolved_by,
            notes=conversation.escalation_notes,
            customer=customer_view(customer),
            tags=conversation.tags,
            properties=conversation.properties,
            last_message=text[:_PREVIEW_CHARS] if text else None,
        )
        for conversation, customer, text in rows
    ]


@router.post("/tenants/{tenant_id}/escalations/{conversation_id}/claim", status_code=204)
def claim_escalation(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_ACT)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _act(
        db, tenant_id, conversation_id,
        lambda: handoff.claim(
            db, conversation_id=conversation_id, agent_name=session.name, now=datetime.now(UTC)
        ),
    )


@router.post("/tenants/{tenant_id}/escalations/{conversation_id}/messages", response_model=MessageView)
def reply_to_visitor(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: ReplyRequest,
    session: Annotated[AdminSession, Depends(_ACT)],
    db: Annotated[Session, Depends(get_db)],
) -> Message:
    return _act(
        db, tenant_id, conversation_id,
        lambda: handoff.reply(
            db, conversation_id=conversation_id, agent_name=session.name, text=body.text,
            now=datetime.now(UTC),
        ),
    )


@router.post("/tenants/{tenant_id}/escalations/{conversation_id}/close", status_code=204)
def close_escalation(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: CloseRequest,
    session: Annotated[AdminSession, Depends(_ACT)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _act(
        db, tenant_id, conversation_id,
        lambda: handoff.close(
            db, conversation_id=conversation_id, agent_name=session.name, now=datetime.now(UTC),
            notes=body.notes,
        ),
    )


@router.post("/tenants/{tenant_id}/escalations/{conversation_id}/resolve", status_code=204)
def resolve_escalation(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: CloseRequest,
    session: Annotated[AdminSession, Depends(_ACT)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _act(
        db, tenant_id, conversation_id,
        lambda: handoff.resolve(
            db, conversation_id=conversation_id, agent_name=session.name, now=datetime.now(UTC),
            notes=body.notes,
        ),
    )
