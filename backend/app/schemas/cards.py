from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


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


Card = Annotated[ActionCard | ProductCard | DividerCard, Field(discriminator="type")]
