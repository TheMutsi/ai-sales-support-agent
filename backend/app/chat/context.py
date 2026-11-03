"""Properties and tags on a conversation: small public hints (`device: iphone`, a
`landing-sale` tag) that the agent, the rules and the analysis can read.

They are set from the browser, so anyone can claim anything; they are never a reason to allow
something. Whatever needs a real check (a plan, an order) is decided by code that validates it,
and a property only changes how we talk or what we offer. The limits keep them small: they
travel on every trace and sit in the conversation row.
"""

import re
import uuid

from sqlalchemy.orm import Session

from app.chat.turns import _lock

MAX_PROPERTIES = 20
MAX_TAGS = 20
MAX_VALUE_LENGTH = 100

PROPERTY_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
TAG = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,39}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class ContextError(Exception):
    """The update breaks a rule. `code` is what the API reports."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def update_context(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    properties: dict[str, str | None],
    add_tags: list[str],
    remove_tags: list[str],
) -> tuple[dict[str, str], list[str]]:
    """Merges the change into the conversation, under its row lock. A property set to `None`
    is removed. Returns what the conversation holds afterwards."""
    for key, value in properties.items():
        if not PROPERTY_KEY.match(key):
            raise ContextError("invalid_property_key")
        if value is not None and (len(value) > MAX_VALUE_LENGTH or _CONTROL_CHARS.search(value)):
            raise ContextError("invalid_property_value")
    if any(not TAG.match(tag) for tag in add_tags):
        raise ContextError("invalid_tag")

    conversation = _lock(db, conversation_id)
    merged = {**conversation.properties}
    for key, value in properties.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    tags = [t for t in conversation.tags if t not in remove_tags]
    tags += [t for t in dict.fromkeys(add_tags) if t not in tags]

    if len(merged) > MAX_PROPERTIES:
        db.rollback()
        raise ContextError("too_many_properties")
    if len(tags) > MAX_TAGS:
        db.rollback()
        raise ContextError("too_many_tags")

    conversation.properties = merged
    conversation.tags = tags
    db.commit()
    return merged, tags
