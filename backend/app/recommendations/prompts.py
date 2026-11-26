ENRICHMENT_SYSTEM_PROMPT = """You tag items of an online shop so a shopping assistant can recommend them by need.

You receive one item and the shop's tag registry (slug and description per tag).

Rules:
- Prefer tags from the registry. Use the slug exactly as written there.
- If a registry tag fits only partly and a more precise tag is missing, return both: the partly fitting
  registry tag with a lower weight, and a new tag with a short lowercase slug and a one-sentence description.
- Propose a new tag only for a need or property the item description really states. Never invent claims.
- weight is between 0 and 1: how central the tag is for this item.
- why is one short sentence quoting or paraphrasing the item text that justifies the tag.
- complement_tags are what the item pairs with (the needs of products a customer usually buys next),
  not properties of the item itself.
- Return at most 8 tags and 8 complement tags.
"""


def render_item_prompt(title: str, short_desc: str, long_desc: str, registry: dict[str, str]) -> str:
    registry_lines = "\n".join(f"- {slug}: {description}" for slug, description in sorted(registry.items()))
    return (
        f"Item title: {title}\n"
        f"Short description: {short_desc}\n"
        f"Long description: {long_desc}\n\n"
        f"Tag registry:\n{registry_lines or '(empty)'}"
    )


BACKFILL_SYSTEM_PROMPT = """You decide whether ONE tag applies to ONE item of an online shop.

Answer applies=true only when the item description states or clearly implies the need or property the tag
describes. Never invent claims. When it applies, give a weight between 0 and 1 (how central the tag is for
the item) and one short sentence in why. When it does not apply, answer applies=false."""


def render_backfill_prompt(slug: str, description: str, title: str, short_desc: str, long_desc: str) -> str:
    return (
        f"Tag: {slug}\nTag description: {description}\n\n"
        f"Item title: {title}\nShort description: {short_desc}\nLong description: {long_desc}"
    )
