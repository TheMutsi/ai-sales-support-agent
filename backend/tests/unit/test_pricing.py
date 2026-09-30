"""Unit tests for upgrade price quoting."""

import pytest

from app.business.pricing import calculate_upgrade_price
from app.db.models import Plan


def _plan(slug: str, price_cents: int, billing_period: str = "monthly") -> Plan:
    return Plan(slug=slug, name=slug.title(), price_cents=price_cents, billing_period=billing_period)


def test_calculates_price_delta_for_upgrade():
    starter = _plan("starter", 2900)
    pro = _plan("pro", 9900)

    quote = calculate_upgrade_price(starter, pro)

    assert quote.current_plan_slug == "starter"
    assert quote.target_plan_slug == "pro"
    assert quote.current_price_cents == 2900
    assert quote.target_price_cents == 9900
    assert quote.price_delta_cents == 7000
    assert quote.billing_period == "monthly"


def test_raises_on_mismatched_billing_periods():
    monthly = _plan("pro", 9900, billing_period="monthly")
    annual = _plan("pro-annual", 99000, billing_period="annual")

    with pytest.raises(ValueError, match="different billing periods"):
        calculate_upgrade_price(monthly, annual)
