"""Agent-facing tool: create a support ticket.

`category`/`priority` are `StrEnum`s, not raw strings, specifically because
`Ticket.category`/`Ticket.priority` are unconstrained string columns in the
DB (app/db/models.py, enforced nowhere at the DB level) — the enum is what
constrains values passed through *this* function. It doesn't stop a future
write path (a script, an admin endpoint) from inserting something else
directly; that would need a DB-level check constraint.
"""

import uuid

from app.db.models import Ticket
from app.db.session import SessionLocal
from app.schemas.tools import TicketCategory, TicketPriority, TicketReceipt
from app.tools._shared import require_customer


def create_support_ticket(
    customer_id: uuid.UUID,
    category: TicketCategory,
    subject: str,
    description: str,
    priority: TicketPriority = TicketPriority.MEDIUM,
) -> TicketReceipt:
    with SessionLocal() as session:
        require_customer(session, customer_id)

        ticket = Ticket(
            customer_id=customer_id,
            category=category.value,
            subject=subject,
            description=description,
            priority=priority.value,
        )
        session.add(ticket)
        session.commit()
        session.refresh(ticket)

        return TicketReceipt(
            ticket_id=ticket.id, status=ticket.status, created_at=ticket.created_at
        )
