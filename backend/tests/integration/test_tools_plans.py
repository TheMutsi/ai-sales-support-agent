"""Integration tests for the plan tools."""

import pytest
from sqlalchemy.orm import Session

from app.tools.errors import ToolLookupError
from app.tools.plans import get_plan_details, list_plans


def test_returns_known_plan(seeded_db: Session):
    plan = get_plan_details("pro")

    assert plan.name == "Pro"
    assert plan.price_cents == 9900
    assert "advanced_reporting" in plan.features


def test_lists_every_plan_cheapest_first(seeded_db: Session):
    plans = list_plans()

    assert [plan.slug for plan in plans] == ["starter", "pro", "enterprise"]
    assert [plan.price_cents for plan in plans] == [2900, 9900, 49900]


def test_raises_for_unknown_slug(seeded_db: Session):
    with pytest.raises(ToolLookupError, match="No plan"):
        get_plan_details("nonexistent")
