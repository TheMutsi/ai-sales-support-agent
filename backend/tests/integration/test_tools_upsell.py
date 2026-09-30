"""Integration tests for the upgrade-path tools: eligibility, pricing, checkout.

The underlying decision logic (is this eligible, what's the price delta) is
already unit-tested in `tests/unit/test_eligibility.py` and
`tests/unit/test_pricing.py` against synthetic data — these tests only prove
that the tool layer resolves a customer_id into the right DB rows and wires
them into that logic correctly.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.models import Customer
from app.tools.errors import ToolLookupError, UpgradeNotEligibleError
from app.tools.upsell import (
    calculate_upgrade_price,
    check_upgrade_eligibility,
    create_upgrade_checkout,
)


def test_eligible_for_active_subscription(seeded_db: Session):
    customer = seeded_db.query(Customer).filter_by(email="ava.chen@northlightstudio.com").one()

    result = check_upgrade_eligibility(customer.id)

    assert result.eligible is True


def test_not_eligible_for_past_due_subscription(seeded_db: Session):
    customer = (
        seeded_db.query(Customer).filter_by(email="helena.ostrowski@ridgeportlegal.com").one()
    )

    result = check_upgrade_eligibility(customer.id)

    assert result.eligible is False
    assert "past_due" in result.reason


def test_raises_for_unknown_customer_id_on_eligibility(seeded_db: Session):
    with pytest.raises(ToolLookupError, match="No subscription"):
        check_upgrade_eligibility(uuid.uuid4())


def test_calculates_price_delta_between_real_plans(seeded_db: Session):
    customer = (
        seeded_db.query(Customer).filter_by(email="priya.anand@bluecrestlogistics.com").one()
    )  # pro

    quote = calculate_upgrade_price(customer.id, "enterprise")

    assert quote.current_plan_slug == "pro"
    assert quote.target_plan_slug == "enterprise"
    assert quote.price_delta_cents == 49900 - 9900


def test_creates_checkout_for_eligible_customer(seeded_db: Session):
    customer = (
        seeded_db.query(Customer).filter_by(email="ava.chen@northlightstudio.com").one()
    )  # starter, active

    checkout = create_upgrade_checkout(customer.id, "pro")

    assert checkout.target_plan_slug == "pro"
    assert checkout.checkout_url.startswith("https://acmeflow.example/demo-checkout/")
    assert checkout.price_quote.price_delta_cents == 9900 - 2900


def test_refuses_checkout_when_not_eligible(seeded_db: Session):
    customer = (
        seeded_db.query(Customer).filter_by(email="helena.ostrowski@ridgeportlegal.com").one()
    )  # past_due

    with pytest.raises(UpgradeNotEligibleError, match="past_due"):
        create_upgrade_checkout(customer.id, "enterprise")
