"""Unit tests for the upsell decision tree.

Mirrors the real seed catalog's shape (`data/seed/plans.json`: starter/pro/
enterprise, each a feature superset of the one below) so these tests double
as documentation of how the real plan ladder behaves, without depending on
the seed file itself — a change to the seed data shouldn't break these.
"""

from app.business.upsell_rules import evaluate_upsell
from app.db.models import Plan, Subscription


def _plan(slug: str, price_cents: int, features: list[str]) -> Plan:
    return Plan(
        slug=slug,
        name=slug.title(),
        price_cents=price_cents,
        billing_period="monthly",
        features=features,
    )


def _subscription(status: str = "active") -> Subscription:
    return Subscription(status=status)


STARTER = _plan("starter", 2900, ["basic_reporting"])
PRO = _plan("pro", 9900, ["basic_reporting", "advanced_reporting", "integrations"])
ENTERPRISE = _plan("enterprise", 49900, ["basic_reporting", "advanced_reporting", "integrations", "sso"])
CATALOG = [STARTER, PRO, ENTERPRISE]


def test_no_upsell_when_current_plan_already_has_feature():
    decision = evaluate_upsell("basic_reporting", STARTER, _subscription(), CATALOG)

    assert decision.recommended is False
    assert decision.recommendation is None
    assert "already" in decision.reason.lower()


def test_no_upsell_when_no_plan_offers_feature():
    decision = evaluate_upsell("white_glove_onboarding", STARTER, _subscription(), CATALOG)

    assert decision.recommended is False
    assert decision.recommendation is None


def test_no_upsell_when_subscription_not_eligible():
    decision = evaluate_upsell("advanced_reporting", STARTER, _subscription("canceled"), CATALOG)

    assert decision.recommended is False
    assert decision.recommendation is None
    assert "canceled" in decision.reason


def test_recommends_cheapest_plan_with_feature():
    decision = evaluate_upsell("advanced_reporting", STARTER, _subscription(), CATALOG)

    assert decision.recommended is True
    assert decision.recommendation.target_plan_slug == "pro"
    assert decision.recommendation.unlocks_feature == "advanced_reporting"
    assert decision.recommendation.price_quote.price_delta_cents == 7000


def test_recommends_next_tier_up_not_furthest_tier():
    decision = evaluate_upsell("sso", PRO, _subscription(), CATALOG)

    assert decision.recommended is True
    assert decision.recommendation.target_plan_slug == "enterprise"
