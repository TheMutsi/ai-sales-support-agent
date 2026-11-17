import uuid

from app.business import eligibility, pricing, upsell_rules
from app.db.models import Plan
from app.db.session import SessionLocal
from app.schemas.business import EligibilityResult, PriceQuote, UpsellDecision
from app.schemas.tools import CheckoutSession
from app.tools._shared import require_current_subscription, require_plan
from app.tools.errors import UpgradeNotEligibleError

_DEMO_CHECKOUT_BASE_URL = "https://mewflow.example/demo-checkout"


def evaluate_upsell(customer_id: uuid.UUID, feature: str) -> UpsellDecision:
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

        eligibility_result = eligibility.check_upgrade_eligibility(subscription)
        if not eligibility_result.eligible:
            raise UpgradeNotEligibleError(eligibility_result.reason)

        price_quote = pricing.calculate_upgrade_price(subscription.plan, target_plan)
        return CheckoutSession(
            checkout_url=f"{_DEMO_CHECKOUT_BASE_URL}/{uuid.uuid4()}",
            target_plan_slug=target_plan.slug,
            price_quote=price_quote,
        )
