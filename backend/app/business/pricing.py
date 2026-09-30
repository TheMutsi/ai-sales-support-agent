"""Upgrade price quoting.

Quotes the plain price difference between a customer's current plan and a
target plan. No proration: AcmeFlow's simulated billing has no mid-cycle
invoicing engine, so the honest answer this layer can give is the full
new-plan price, not a prorated partial-period estimate that would need
billing-cycle state this project doesn't model.
"""

from app.db.models import Plan
from app.schemas.business import PriceQuote


def calculate_upgrade_price(current_plan: Plan, target_plan: Plan) -> PriceQuote:
    if target_plan.billing_period != current_plan.billing_period:
        raise ValueError(
            f"Cannot compare plans on different billing periods: "
            f"'{current_plan.slug}' is {current_plan.billing_period}, "
            f"'{target_plan.slug}' is {target_plan.billing_period}."
        )
    return PriceQuote(
        current_plan_slug=current_plan.slug,
        target_plan_slug=target_plan.slug,
        current_price_cents=current_plan.price_cents,
        target_price_cents=target_plan.price_cents,
        price_delta_cents=target_plan.price_cents - current_plan.price_cents,
        billing_period=current_plan.billing_period,
    )
