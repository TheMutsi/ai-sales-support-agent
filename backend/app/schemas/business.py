from pydantic import BaseModel


class EligibilityResult(BaseModel):
    eligible: bool
    reason: str


class PriceQuote(BaseModel):
    current_plan_slug: str
    target_plan_slug: str
    current_price_cents: int
    target_price_cents: int
    price_delta_cents: int
    billing_period: str


class UpsellRecommendation(BaseModel):
    target_plan_slug: str
    target_plan_name: str
    unlocks_feature: str
    price_quote: PriceQuote
    reason: str


class UpsellDecision(BaseModel):
    recommended: bool
    recommendation: UpsellRecommendation | None = None
    reason: str
