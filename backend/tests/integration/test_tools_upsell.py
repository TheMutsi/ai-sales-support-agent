"""Integration tests for the upgrade-path tools: which feature justifies an
upgrade, eligibility, pricing, checkout.

The underlying decision logic (does this plan have the feature, is the
subscription eligible, what's the price delta) is already unit-tested in
`tests/unit/test_eligibility.py`, `test_pricing.py`, and
`test_upsell_rules.py` against synthetic data — these tests only prove that
the tool layer resolves a customer_id into the right DB rows and wires them
into that logic correctly.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.tools.errors import ToolLookupError, UpgradeNotEligibleError
from app.tools.upsell import (
    calculate_upgrade_price,
    check_upgrade_eligibility,
    create_upgrade_checkout,
    evaluate_upsell,
)
from tests.integration.conftest import customer_by_email


def test_recommends_a_real_plan_for_a_missing_feature(seeded_db: Session):
    customer = customer_by_email(seeded_db, "ava.chen@northlightstudio.com")  # starter, active

    decision = evaluate_upsell(customer.id, "advanced_reporting")

    assert decision.recommended is True
    assert decision.recommendation.target_plan_slug == "pro"


def test_no_upsell_when_the_current_plan_already_has_the_feature(seeded_db: Session):
    customer = customer_by_email(seeded_db, "priya.anand@bluecrestlogistics.com")  # pro

    decision = evaluate_upsell(customer.id, "advanced_reporting")

    assert decision.recommended is False
    assert decision.recommendation is None


def test_eligible_for_active_subscription(seeded_db: Session):
    customer = customer_by_email(seeded_db, "ava.chen@northlightstudio.com")

    result = check_upgrade_eligibility(customer.id)

    assert result.eligible is True


def test_not_eligible_for_past_due_subscription(seeded_db: Session):
    customer = customer_by_email(seeded_db, "helena.ostrowski@ridgeportlegal.com")

    result = check_upgrade_eligibility(customer.id)

    assert result.eligible is False
    assert "past_due" in result.reason


def test_raises_for_unknown_customer_id_on_eligibility(seeded_db: Session):
    with pytest.raises(ToolLookupError, match="No customer"):
        check_upgrade_eligibility(uuid.uuid4())


def test_calculates_price_delta_between_real_plans(seeded_db: Session):
    customer = customer_by_email(seeded_db, "priya.anand@bluecrestlogistics.com")  # pro

    quote = calculate_upgrade_price(customer.id, "enterprise")

    assert quote.current_plan_slug == "pro"
    assert quote.target_plan_slug == "enterprise"
    assert quote.price_delta_cents == 49900 - 9900


def test_creates_checkout_for_eligible_customer(seeded_db: Session):
    customer = customer_by_email(seeded_db, "ava.chen@northlightstudio.com")  # starter, active

    checkout = create_upgrade_checkout(customer.id, "pro")

    assert checkout.target_plan_slug == "pro"
    assert checkout.checkout_url.startswith("https://acmeflow.example/demo-checkout/")
    assert checkout.price_quote.price_delta_cents == 9900 - 2900


def test_refuses_checkout_when_not_eligible(seeded_db: Session):
    customer = customer_by_email(seeded_db, "helena.ostrowski@ridgeportlegal.com")  # past_due

    with pytest.raises(UpgradeNotEligibleError, match="past_due"):
        create_upgrade_checkout(customer.id, "enterprise")


def test_refuses_checkout_for_the_customers_current_plan(seeded_db: Session):
    customer = customer_by_email(seeded_db, "priya.anand@bluecrestlogistics.com")  # already pro

    with pytest.raises(UpgradeNotEligibleError, match="Already on"):
        create_upgrade_checkout(customer.id, "pro")
