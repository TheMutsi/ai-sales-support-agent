"""Integration tests for the get_customer_context tool.

Requires a real Postgres (`alembic upgrade head`) — the `seeded_db` fixture
(conftest.py) loads plans/customers/subscriptions from `data/seed/`.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.models import Customer
from app.tools.customers import get_customer_context
from app.tools.errors import ToolLookupError


def test_returns_identity_and_current_subscription(seeded_db: Session):
    customer = seeded_db.query(Customer).filter_by(email="priya.anand@bluecrestlogistics.com").one()

    context = get_customer_context(customer.id)

    assert context.name == "Priya Anand"
    assert context.email == "priya.anand@bluecrestlogistics.com"
    assert context.status == "active"
    assert context.subscription is not None
    assert context.subscription.status == "active"
    assert context.subscription.plan.slug == "pro"


def test_raises_for_unknown_customer_id(seeded_db: Session):
    with pytest.raises(ToolLookupError, match="No customer"):
        get_customer_context(uuid.uuid4())
