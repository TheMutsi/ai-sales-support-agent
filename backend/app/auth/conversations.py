"""Creating conversations and attaching a customer to one.

A visitor starts with an anonymous conversation. When they identify (the shop's
login token or a one-time code) the customer is attached to *that* conversation,
so the history carries over. Two rules keep this safe:

- A conversation that already has a customer is never reassigned. If someone else
  identifies in the same browser they get a conversation of their own and the first
  customer's stays intact.
- A conversation id the caller presents is only used if it exists and belongs to the
  same tenant; anything else starts a fresh one. The row is locked while deciding, so
  two simultaneous logins can't both take the same anonymous conversation.
"""

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
    """The conversation a just-authenticated customer continues in."""
    conversation = None
    if conversation_id is not None:
        conversation = (
            db.query(Conversation)
            .filter_by(id=conversation_id, tenant_id=tenant_id)
            # Explicit, so a row this session already loaded is re-read under the
            # lock instead of trusting stale attributes (recent SQLAlchemy implies it).
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )

    if conversation is None or conversation.customer_id not in (None, customer_id):
        # No rollback: the session isn't ours, and the commit below releases the lock.
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
    """The conversation a visitor who proved an order continues in. No customer is attached:
    an order id is a weak proof, so the conversation stays unlinked and a later, stronger login
    (a one-time code) can still claim it. A conversation that already belongs to a customer is
    never reused, for the same reason `resolve_for_login` never reassigns one."""
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
