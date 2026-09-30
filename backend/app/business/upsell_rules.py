"""The upsell decision tree.

Answers one question: should the agent recommend upgrading to unlock a
specific feature, and if so, to which plan? The three checks below run in
that order and each can end the decision for a different reason — already
supported, no plan offers it, or the subscription isn't eligible to upgrade.
Collapsing them into a single boolean would lose the ability to give the
agent (and ultimately the customer) a specific, honest reason instead of a
bare no; that's why `UpsellDecision.reason` is always populated, not just
attached on the negative path.

The LLM never runs this logic itself — per Core Principle #1, "does this plan
support X" and "which plan is cheapest to add" are facts a function computes,
not something a prompt decides.
"""

from app.business.eligibility import check_upgrade_eligibility
from app.business.pricing import calculate_upgrade_price
from app.db.models import Plan, Subscription
from app.schemas.business import UpsellDecision, UpsellRecommendation


def evaluate_upsell(
    feature: str,
    current_plan: Plan,
    subscription: Subscription,
    available_plans: list[Plan],
) -> UpsellDecision:
    if feature in current_plan.features:
        return UpsellDecision(
            recommended=False,
            reason=f"'{current_plan.name}' already includes '{feature}'.",
        )

    target_plan = _cheapest_plan_with_feature(feature, available_plans, exclude_slug=current_plan.slug)
    if target_plan is None:
        return UpsellDecision(
            recommended=False,
            reason=f"No plan in the catalog offers '{feature}'.",
        )

    eligibility = check_upgrade_eligibility(subscription)
    if not eligibility.eligible:
        return UpsellDecision(recommended=False, reason=eligibility.reason)

    price_quote = calculate_upgrade_price(current_plan, target_plan)
    reason = f"'{feature}' is available on {target_plan.name}, not on {current_plan.name}."
    return UpsellDecision(
        recommended=True,
        recommendation=UpsellRecommendation(
            target_plan_slug=target_plan.slug,
            target_plan_name=target_plan.name,
            unlocks_feature=feature,
            price_quote=price_quote,
            reason=reason,
        ),
        reason=reason,
    )


def _cheapest_plan_with_feature(feature: str, plans: list[Plan], exclude_slug: str) -> Plan | None:
    candidates = [p for p in plans if p.slug != exclude_slug and feature in p.features]
    if not candidates:
        return None
    return min(candidates, key=lambda p: p.price_cents)
