"""Cards: structured things a reply can show next to its text, drawn by the widget.

A card is a message part, like text or an image. The server builds them from what the turn
really did (never from the model's words), stores them with the reply, and the widget draws one
component per type. New kinds (a carousel) are new members of the union, nothing else.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class CardImage(BaseModel):
    """A path on this API (the widget resolves it against its own API base) or an absolute URL."""

    url: str
    alt: str


class CardAction(StrEnum):
    """What a button does: a closed set the server mints, so a click is decided by rules and
    never read by a model. A new button is a new member here and a row in the step that handles it."""

    CONFIRM_ORDER = "confirm_order"  # "yes, this is the order I mean"
    CHOOSE_ORDER = "choose_order"  # takes the card's `order_id`
    KEEP_ORDER = "keep_order"
    CONFIRM_CANCEL = "confirm_cancel"
    TAKE_REFUND = "take_refund"
    TAKE_CREDITS = "take_credits"
    DECLINE_OFFER = "decline_offer"


class ActionCard(BaseModel):
    """Something the visitor can pick. Clicking it sends `action` (and `order_id`), not text: the
    server checks it was really offered and applies it with rules, no model. `message` is what
    the click says in the conversation, taken from here and never from the client. Cards stored
    before `action` existed have none; they can still be shown but not clicked."""

    type: Literal["action"] = "action"
    id: str
    title: str
    subtitle: str | None = None
    badge: str | None = None
    message: str
    action: CardAction | None = None
    order_id: str | None = None


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
