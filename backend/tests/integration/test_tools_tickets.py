"""Integration tests for the create_support_ticket tool."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.models import Ticket
from app.schemas.tools import TicketCategory, TicketPriority
from app.tools.errors import ToolLookupError
from app.tools.tickets import create_support_ticket
from tests.integration.conftest import customer_by_email


def test_persists_a_ticket_for_a_real_customer(seeded_db: Session):
    customer = customer_by_email(seeded_db, "ava.chen@northlightstudio.com")

    receipt = create_support_ticket(
        customer.id,
        category=TicketCategory.BILLING,
        subject="Duplicate charge",
        description="Charged twice for October.",
        priority=TicketPriority.HIGH,
    )

    assert receipt.status == "open"
    stored = seeded_db.get(Ticket, receipt.ticket_id)
    assert stored.category == "billing"
    assert stored.priority == "high"
    assert stored.created_by == "agent"


def test_defaults_to_medium_priority(seeded_db: Session):
    customer = customer_by_email(seeded_db, "ava.chen@northlightstudio.com")

    receipt = create_support_ticket(
        customer.id,
        category=TicketCategory.TECHNICAL,
        subject="Login issue",
        description="Can't log in.",
    )

    stored = seeded_db.get(Ticket, receipt.ticket_id)
    assert stored.priority == "medium"


def test_raises_for_unknown_customer_id(seeded_db: Session):
    with pytest.raises(ToolLookupError, match="No customer"):
        create_support_ticket(
            uuid.uuid4(), category=TicketCategory.OTHER, subject="x", description="x"
        )
