from app.business.eligibility import check_upgrade_eligibility
from app.db.models import Subscription


def _subscription(status: str) -> Subscription:
    return Subscription(status=status)


def test_active_subscription_is_eligible():
    result = check_upgrade_eligibility(_subscription("active"))

    assert result.eligible is True


def test_canceled_subscription_is_not_eligible():
    result = check_upgrade_eligibility(_subscription("canceled"))

    assert result.eligible is False
    assert "canceled" in result.reason


def test_past_due_subscription_is_not_eligible():
    result = check_upgrade_eligibility(_subscription("past_due"))

    assert result.eligible is False
    assert "past_due" in result.reason
