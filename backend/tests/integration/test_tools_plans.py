"""Integration tests for the get_plan_details tool."""

import pytest
from sqlalchemy.orm import Session

from app.tools.errors import ToolLookupError
from app.tools.plans import get_plan_details


def test_returns_known_plan(seeded_db: Session):
    plan = get_plan_details("pro")

    assert plan.name == "Pro"
    assert plan.price_cents == 9900
    assert "advanced_reporting" in plan.features


def test_raises_for_unknown_slug(seeded_db: Session):
    with pytest.raises(ToolLookupError, match="No plan"):
        get_plan_details("nonexistent")
