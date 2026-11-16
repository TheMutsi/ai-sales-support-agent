from app.db.models import Subscription
from app.schemas.business import EligibilityResult

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
