"""Cards: structured things a reply can show next to its text, drawn by the widget.

A card is a message part, like text or an image. The server builds them from what the turn
really did (never from the model's words), stores them with the reply, and the widget draws one
component per type. New kinds (a carousel) are new members of the union, nothing else.
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
    # A price shown struck through before `price` (what a gift would have cost).
    compare_price: str | None = None
    badge: str | None = None
    image: CardImage
    # More pictures of the same thing, drawn stacked behind the first.
    more_images: list[CardImage] = Field(default_factory=list)


class DividerCard(BaseModel):
    """A mark between groups of cards (a "+" between a gift and the choices that come with it)."""

    type: Literal["divider"] = "divider"
    id: str
    label: str = ""


Card = Annotated[ActionCard | ProductCard | DividerCard, Field(discriminator="type")]
