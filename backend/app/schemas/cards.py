from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class CardImage(BaseModel):
    url: str
    alt: str


class CardAction(StrEnum):
    CONFIRM_ORDER = "confirm_order"
    CHOOSE_ORDER = "choose_order"
    KEEP_ORDER = "keep_order"
    CONFIRM_CANCEL = "confirm_cancel"
    TAKE_REFUND = "take_refund"
    TAKE_CREDITS = "take_credits"
    DECLINE_OFFER = "decline_offer"


class ActionCard(BaseModel):
    type: Literal["action"] = "action"
    id: str
    title: str
    subtitle: str | None = None
    badge: str | None = None
    message: str
    action: CardAction | None = None
    order_id: str | None = None


class ProductCard(BaseModel):
    type: Literal["product"] = "product"
    id: str
    name: str
    subtitle: str | None = None
    price: str | None = None
    compare_price: str | None = None
    badge: str | None = None
    image: CardImage
    more_images: list[CardImage] = Field(default_factory=list)


class DividerCard(BaseModel):
    type: Literal["divider"] = "divider"
    id: str
    label: str = ""


class RecommendationTemplate(StrEnum):
    PRODUCT_CARD = "product_card"


class RecommendationCard(BaseModel):
    type: Literal["recommendation"] = "recommendation"
    id: str
    template: RecommendationTemplate
    title: str
    description: str | None = None
    image: CardImage
    rating: float | None = Field(default=None, ge=0, le=5)
    url: str | None = None
    price: str | None = None
    compare_price: str | None = None
    offer_label: str | None = None
    why: str | None = None

    @field_validator("url")
    @classmethod
    def _url_is_http_or_https(cls, value: str | None) -> str | None:
        if value is not None and not value.lower().startswith(("http://", "https://")):
            raise ValueError("a recommendation link must be an http or https address")
        return value

    @field_validator("image")
    @classmethod
    def _image_is_http_https_or_relative(cls, value: CardImage) -> CardImage:
        url = value.url
        if not (url.lower().startswith(("http://", "https://")) or (url.startswith("/") and not url.startswith("//"))):
            raise ValueError("a recommendation picture must be an http or https address or a relative path")
        return value


Card =Annotated[
    ActionCard | ProductCard | DividerCard | RecommendationCard, Field(discriminator="type")
]


def is_a_card_still_readable(card: object) -> bool:
    if not isinstance(card, dict):
        return True
    if card.get("type") == "recommendation":
        return card.get("template") in {template.value for template in RecommendationTemplate}
    return card.get("type") in {"action", "product", "divider"}
