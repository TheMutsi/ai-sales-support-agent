import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.scopes import IdentityLevel
from app.db.models import Conversation


def create_anonymous(db: Session, *, tenant_id: uuid.UUID, now: datetime) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(), tenant_id=tenant_id, created_at=now, last_activity_at=now
    )
    db.add(conversation)
    db.commit()
    return conversation


def _new_identified(
    db: Session, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, level: IdentityLevel, now: datetime
) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        customer_id=customer_id,
        identity_level=level.value,
        linked_via=level.value,
        customer_linked_at=now,
        created_at=now,
        last_activity_at=now,
    )
    db.add(conversation)
    db.commit()
    return conversation


def resolve_for_login(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    level: IdentityLevel,
    conversation_id: uuid.UUID | None,
    now: datetime,
) -> Conversation:
    conversation = None
    if conversation_id is not None:
        conversation = (
            db.query(Conversation)
            .filter_by(id=conversation_id, tenant_id=tenant_id)
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )

    if conversation is None or conversation.customer_id not in (None, customer_id):
        return _new_identified(db, tenant_id=tenant_id, customer_id=customer_id, level=level, now=now)

    if conversation.customer_id is None:
        conversation.customer_id = customer_id
        conversation.identity_level = level.value
        conversation.linked_via = level.value
        conversation.customer_linked_at = now
    conversation.last_activity_at = now
    db.commit()
    return conversation


def resolve_for_order_lookup(
    db: Session, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID | None, now: datetime
) -> Conversation:
    conversation = None
    if conversation_id is not None:
        conversation = (
            db.query(Conversation)
            .filter_by(id=conversation_id, tenant_id=tenant_id)
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )
    if conversation is None or conversation.customer_id is not None:
        conversation = Conversation(
            id=uuid.uuid4(), tenant_id=tenant_id, created_at=now, last_activity_at=now
        )
        db.add(conversation)
    conversation.identity_level = IdentityLevel.ORDER_LOOKUP.value
    conversation.linked_via = IdentityLevel.ORDER_LOOKUP.value
    conversation.last_activity_at = now
    db.commit()
    return conversation
