"""The back office's view of conversations: who talked, what was said, how they identified.

Reading messages is access to personal data, so it needs its own permission
(`conversations:read`) and a conversation is only ever shown under its own tenant. The customer is
shown by name and a masked email, like the identification audit.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.admin.permissions import Permission
from app.api.admin_deps import error, require_tenant_permission
from app.auth.audit import mask_email
from app.db.models import Conversation, Customer, IdentificationEvent, Message
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

_PREVIEW_CHARS = 120
_MAX_MESSAGES = 500  # a conversation is about ten messages; this is a ceiling, not a page


class CustomerView(BaseModel):
    name: str
    email_masked: str


class ConversationSummary(BaseModel):
    id: uuid.UUID
    identity_level: str
    customer: CustomerView | None
    created_at: datetime
    last_activity_at: datetime
    message_count: int
    first_message: str | None


class MessageView(BaseModel):
    seq: int
    role: str
    kind: str
    content: str
    created_at: datetime


class IdentificationView(BaseModel):
    method: str
    outcome: str
    reason: str | None
    email_masked: str | None
    created_at: datetime


class ConversationDetail(BaseModel):
    id: uuid.UUID
    identity_level: str
    linked_via: str | None
    customer: CustomerView | None
    created_at: datetime
    last_activity_at: datetime
    messages: list[MessageView]
    identification: list[IdentificationView]


def _customer(customer: Customer | None) -> CustomerView | None:
    return CustomerView(name=customer.name, email_masked=mask_email(customer.email)) if customer else None


@router.get("/tenants/{tenant_id}/conversations", response_model=list[ConversationSummary])
def list_conversations(
    tenant_id: uuid.UUID,
    _: Annotated[object, Depends(require_tenant_permission(Permission.CONVERSATIONS_READ))],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
) -> list[ConversationSummary]:
    """Newest activity first; pass the last item's `last_activity_at` as `before` for the next page."""
    query = (
        select(Conversation, Customer, Message.content)
        .outerjoin(Customer, Customer.id == Conversation.customer_id)
        .outerjoin(
            Message, and_(Message.conversation_id == Conversation.id, Message.seq == 1)
        )
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.last_activity_at.desc())
        .limit(limit)
    )
    if before is not None:
        query = query.where(Conversation.last_activity_at < before)
    return [
        ConversationSummary(
            id=conversation.id,
            identity_level=conversation.identity_level,
            customer=_customer(customer),
            created_at=conversation.created_at,
            last_activity_at=conversation.last_activity_at,
            message_count=conversation.last_seq,
            first_message=first[:_PREVIEW_CHARS] if first else None,
        )
        for conversation, customer, first in db.execute(query)
    ]


@router.get("/tenants/{tenant_id}/conversations/{conversation_id}", response_model=ConversationDetail)
def read_conversation(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    _: Annotated[object, Depends(require_tenant_permission(Permission.CONVERSATIONS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> ConversationDetail:
    conversation = db.get(Conversation, conversation_id)
    # Another tenant's conversation is "not found", not "forbidden": its existence is not ours to say.
    if conversation is None or conversation.tenant_id != tenant_id:
        raise error(404, "conversation_not_found")
    customer = db.get(Customer, conversation.customer_id) if conversation.customer_id else None
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq)
        .limit(_MAX_MESSAGES)
    )
    events = db.scalars(
        select(IdentificationEvent)
        .where(IdentificationEvent.conversation_id == conversation_id)
        .order_by(IdentificationEvent.created_at)
    )
    return ConversationDetail(
        id=conversation.id,
        identity_level=conversation.identity_level,
        linked_via=conversation.linked_via,
        customer=_customer(customer),
        created_at=conversation.created_at,
        last_activity_at=conversation.last_activity_at,
        messages=[MessageView.model_validate(m, from_attributes=True) for m in messages],
        identification=[IdentificationView.model_validate(e, from_attributes=True) for e in events],
    )
