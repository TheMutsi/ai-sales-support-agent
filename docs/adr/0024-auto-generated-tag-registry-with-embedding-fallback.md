# ADR-0024: Auto-generated tag registry with embedding fallback

- **Status:** Accepted (the tag tables and the ranking rule are built; the enrichment agent and the search are not)
- **Introduced in:** the generic recommendation feature (catalog data layer first; enrichment and search follow)

## Context

To recommend "something firming for dry skin" the assistant needs items described by needs, not just
by text. Curating tags by hand does not scale with a catalog, and free-form tags drift
("firming" versus "tightening"), so two items that should match do not.

## Decision

- **Each tenant has a tag registry** (`recommendation_tags`: slug and description, with an
  embedding). An item's tags live in `item_tags` with a **weight from 0 to 1**, a one-line **why**
  stored at tagging time, a `pinned` flag and an `is_complement` flag (the tag marks what the item
  pairs with, used by cross-sell, ADR-0025).
- **An enrichment agent tags items.** On save, a structured-output call receives the item and the
  whole registry and returns tags with weight and why, plus complement tags. It reuses registry
  tags. When none fits fully it proposes a new, more precise tag and **keeps both**. Before a tag is
  created its description is compared by embedding with the existing ones, and a near-identical one
  is reused.
- **Creating a tag triggers a non-recursive backfill**: only candidate items (those holding the
  partially fitting tag, plus the nearest by embedding) are re-checked, for the new tag only, and a
  backfill can never create tags. Pinned tags are never overwritten. Enrichment is serialized per
  tenant with the repo's advisory lock pattern.
- **Search maps the customer's phrase to one to five tags** chosen only from the registry (the
  output is validated against it) and ranks items in Python. When no tag matches or the best score
  is weak, it falls back to **hybrid search** over item text (embedding plus full-text, fused by
  reciprocal rank, like the knowledge base, ADR-0022).

## Consequences

- Ranking is a sum of weights in Python (`rank_by_tags`) with a relative cut: items scoring below
  half of the best are dropped. The 0.5 is a guess; it needs labelled cases to calibrate, the same
  lesson as the safety threshold.
- Enrichment is asynchronous and can fail; a failure sets `enrichment_status` to `failed` and is
  logged and traced, never swallowed.
- The registry needs merge tools in the back office, because a model keeps adding precise tags.
- The model chooses from words the tenant's registry contains, so it cannot invent a tag at search
  time.

## Alternatives considered

- **Tags written by hand:** rejected, it does not scale and nobody keeps it consistent.
- **Free-form tags with no registry:** rejected, they drift and cannot be validated.
- **Embedding search only:** kept as the fallback, but weak for "needs" phrasing and gives no stored
  reason to show the shopper.
