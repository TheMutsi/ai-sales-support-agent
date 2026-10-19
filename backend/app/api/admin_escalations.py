"""The back office's inbox of escalations: conversations a person has, or is asked to take.

A visitor whose assistant opened a ticket waits here; an agent claims the conversation, writes to
the visitor one to one (the widget polls for it) and closes it, which hands it back to the
assistant and resolves the ticket. Reading needs `escalations:read`, acting `escalations:reply`.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.permissions import Permission
from app.admin.session import AdminSession
from app.api.admin_conversations import CustomerView, MessageView, customer_view
from app.api.admin_deps import error, require_tenant_permission
from app.chat import handoff
from app.chat.handoff import HandoffError
from app.chat.turns import HandoffStatus
from app.db.models import Conversation, Customer, Message, Ticket
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

_PREVIEW_CHARS = 120
_READ = require_tenant_permission(Permission.ESCALATIONS_READ)
_ACT = require_tenant_permission(Permission.ESCALATIONS_REPLY)


class TicketView(BaseModel):
    category: str
    subject: str
    priority: str


class EscalationItem(BaseModel):
    id: uuid.UUID
    handoff_status: str
    agent_name: str | None
    requested_at: datetime | None
    customer: CustomerView | None
    ticket: TicketView | None
    last_message: str | None  # what the visitor said last


class ReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CloseRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


def _conversation_of(db: Session, tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    """Another tenant's conversation is 'not found', not 'forbidden'."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant_id:
        raise error(404, "conversation_not_found")


def _act(db: Session, tenant_id: uuid.UUID, conversation_id: uuid.UUID, do):
    _conversation_of(db, tenant_id, conversation_id)
    try:
        return do()
    except HandoffError as problem:
        raise error(409, problem.code) from None


@router.get("/tenants/{tenant_id}/escalations", response_model=list[EscalationItem])
def list_escalations(
    tenant_id: uuid.UUID,
    _: Annotated[AdminSession, Depends(_READ)],
    db: Annotated[Session, Depends(get_db)],
) -> list[EscalationItem]:
    """Waiting first, longest wait first; then the ones an agent is in."""
    last_message = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id, Message.role == "user")
        .order_by(Message.seq.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Conversation, Customer, Ticket, last_message)
        .outerjoin(Customer, Customer.id == Conversation.customer_id)
        .outerjoin(Ticket, Ticket.id == Conversation.handoff_ticket_id)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.handoff_status.in_((HandoffStatus.WAITING, HandoffStatus.ACTIVE)),
        )
        # 'active' sorts before 'waiting' alphabetically, so order by the state explicitly.
        .order_by(
            (Conversation.handoff_status == HandoffStatus.WAITING).desc(),
            Conversation.handoff_requested_at,
        )
    )
    return [
        EscalationItem(
            id=conversation.id,
            handoff_status=conversation.handoff_status,
            agent_name=conversation.handoff_agent_name,
            requested_at=conversation.handoff_requested_at,
            customer=customer_view(customer),
            ticket=TicketView(category=ticket.category, subject=ticket.subject, priority=ticket.priority)
            if ticket
            else None,
            last_message=text[:_PREVIEW_CHARS] if text else None,
        )
        for conversation, customer, ticket, text in rows
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
