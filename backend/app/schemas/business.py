"""Typed contracts for the business-rules layer.

`app/business/` communicates through these types instead of raw dicts, per
Core Principle #2 (explicit, strongly-typed state) and #3 (strongly-typed
tool inputs/outputs). `UpsellDecision` always carries a `reason`, even when
`recommended` is `False` — the agent graph (`app/agent/`) and the tools layer
(`app/tools/`) both need to explain *why* no upsell was offered (already on
that tier, no plan has the feature, subscription not eligible), not just get
a bare `None`.
"""

from pydantic import BaseModel


class EligibilityResult(BaseModel):
    """Whether a subscription is in a state that allows upgrading at all,
    independent of which feature or target plan is involved."""

    eligible: bool
    reason: str


class PriceQuote(BaseModel):
    """The price difference between a customer's current plan and a target plan."""

    current_plan_slug: str
    target_plan_slug: str
    current_price_cents: int
    target_price_cents: int
    price_delta_cents: int
    billing_period: str


class UpsellRecommendation(BaseModel):
    """A specific, priced upgrade recommendation: switch to `target_plan_slug`
    to unlock `unlocks_feature`."""

    target_plan_slug: str
    target_plan_name: str
    unlocks_feature: str
    price_quote: PriceQuote
    reason: str


class UpsellDecision(BaseModel):
    """The outcome of `evaluate_upsell()`: either a priced recommendation, or a
    reason none applies. `recommendation` is only set when `recommended` is `True`."""

    recommended: bool
    recommendation: UpsellRecommendation | None = None
    reason: str
