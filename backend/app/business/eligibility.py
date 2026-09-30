"""Subscription-state eligibility checks for plan upgrades.

Kept separate from `upsell_rules.py` because it answers a different question:
not "should we recommend unlocking this feature" (a catalog question) but
"is this subscription even in a state that allows upgrading" (a lifecycle
question). Any future flow that just needs a plain "can this customer change
plans" check (not tied to a specific feature) can call this directly instead
of going through the upsell decision tree.
"""

from app.db.models import Subscription
from app.schemas.business import EligibilityResult

# A canceled subscription has no active billing to upgrade; past_due means
# payment already failed, so offering a *more expensive* plan before that's
# resolved would make the situation worse, not better.
_UPGRADE_BLOCKING_STATUSES = {"canceled", "past_due"}


def check_upgrade_eligibility(subscription: Subscription) -> EligibilityResult:
    if subscription.status in _UPGRADE_BLOCKING_STATUSES:
        return EligibilityResult(
            eligible=False,
            reason=(
                f"Subscription status is '{subscription.status}'; "
                "upgrades require an active subscription."
            ),
        )
    return EligibilityResult(eligible=True, reason="Subscription is active.")
