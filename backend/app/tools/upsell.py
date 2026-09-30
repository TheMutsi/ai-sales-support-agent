"""Agent-facing tools for the upgrade path: which feature justifies an
upgrade, eligibility, pricing, and checkout.

Thin wrappers over `app/business/` — the actual decision logic (does this
plan already have the feature, is the subscription eligible, what's the
price delta) lives there and is unit-tested independently. These functions
add only what business logic can't do itself: resolving a customer_id into
the `Subscription`/`Plan` rows business logic operates on, and managing the
DB session.
"""

import uuid

from app.business import eligibility, pricing, upsell_rules
from app.db.models import Plan
from app.db.session import SessionLocal
from app.schemas.business import EligibilityResult, PriceQuote, UpsellDecision
from app.schemas.tools import CheckoutSession
from app.tools._shared import require_current_subscription, require_plan
from app.tools.errors import UpgradeNotEligibleError

# .example is reserved for documentation/testing (RFC 2606) — guarantees this
# can never resolve to a real domain, matching the "simulated checkout,
# clearly labeled demo" requirement from the roadmap.
_DEMO_CHECKOUT_BASE_URL = "https://acmeflow.example/demo-checkout"


def evaluate_upsell(customer_id: uuid.UUID, feature: str) -> UpsellDecision:
    """Should the agent recommend upgrading this customer to unlock `feature`?
    The actual decision tree (already supported / no plan has it / not
    eligible / recommend X) lives in `business/upsell_rules.py` — this is
    its only entry point from the tools layer."""
    with SessionLocal() as session:
        subscription = require_current_subscription(session, customer_id)
        available_plans = session.query(Plan).all()
        return upsell_rules.evaluate_upsell(
            feature, subscription.plan, subscription, available_plans
        )


def check_upgrade_eligibility(customer_id: uuid.UUID) -> EligibilityResult:
    with SessionLocal() as session:
        subscription = require_current_subscription(session, customer_id)
        return eligibility.check_upgrade_eligibility(subscription)


def calculate_upgrade_price(customer_id: uuid.UUID, target_plan_slug: str) -> PriceQuote:
    with SessionLocal() as session:
        subscription = require_current_subscription(session, customer_id)
        target_plan = require_plan(session, target_plan_slug)
        return pricing.calculate_upgrade_price(subscription.plan, target_plan)


def create_upgrade_checkout(customer_id: uuid.UUID, target_plan_slug: str) -> CheckoutSession:
    with SessionLocal() as session:
        subscription = require_current_subscription(session, customer_id)
        target_plan = require_plan(session, target_plan_slug)

        if target_plan.slug == subscription.plan.slug:
            raise UpgradeNotEligibleError(f"Already on {target_plan.name}; nothing to upgrade.")

        # Guardrail from CLAUDE.md: "never create a checkout unless
        # eligibility was actually checked" — enforced here so it can't be
        # skipped by an agent node that forgets to call
        # check_upgrade_eligibility first.
        eligibility_result = eligibility.check_upgrade_eligibility(subscription)
        if not eligibility_result.eligible:
            raise UpgradeNotEligibleError(eligibility_result.reason)

        price_quote = pricing.calculate_upgrade_price(subscription.plan, target_plan)
        return CheckoutSession(
            checkout_url=f"{_DEMO_CHECKOUT_BASE_URL}/{uuid.uuid4()}",
            target_plan_slug=target_plan.slug,
            price_quote=price_quote,
        )
