"""Cards: structured things a reply can show next to its text, drawn by the widget.

A card is a message part, like text or an image. The server builds them from what the turn
really did (never from the model's words), stores them with the reply, and the widget draws one
component per type. New kinds (a coupon, a carousel) are new members of the union, nothing else.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class CardImage(BaseModel):
    """A path on this API (the widget resolves it against its own API base) or an absolute URL."""

    url: str
    alt: str


class ActionCard(BaseModel):
    """Something the visitor can pick: clicking it sends `message` as if they had typed it, so the
    conversation (and the rules behind it) work the same whether they click or write."""

    type: Literal["action"] = "action"
    id: str
    title: str
    subtitle: str | None = None
    badge: str | None = None
    message: str


class ProductCard(BaseModel):
    """A thing for sale (or bought): a small picture that opens large when clicked."""

    type: Literal["product"] = "product"
    id: str
    name: str
    subtitle: str | None = None
    price: str | None = None
    badge: str | None = None
    image: CardImage


class CouponCard(BaseModel):
    """A code the visitor was given."""

    type: Literal["coupon"] = "coupon"
    id: str
    code: str
    title: str
    subtitle: str | None = None


Card = Annotated[ActionCard | ProductCard | CouponCard, Field(discriminator="type")]
