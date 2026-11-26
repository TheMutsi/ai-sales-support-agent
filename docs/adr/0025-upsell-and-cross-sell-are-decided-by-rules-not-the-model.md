# ADR-0025: Upsell and cross-sell are decided by rules, not the model

- **Status:** Accepted (the rules are built and tested; the agent that calls them and the guardrail are not)
- **Introduced in:** the generic recommendation feature (deterministic rules)

## Context

The core principle of this project is that the model never decides a fact a function can compute
(ADR-0002). What to offer next, and at what price, is such a fact.

## Decision

- **Cross-sell** (`app.business.recommendations.cross_sell`): items whose tags match the complement
  tags of the chosen items, excluding the chosen ones and anything the customer already bought.
  When real co-purchase counts from orders exist and point at a valid, not-yet-bought item they
  override the tags; counts that cannot be used fall back to the tags.
- **Upsell** (`upsell`): the next bigger pack of the same product, otherwise the best item for the
  same need one price tier up (`price_tier` over per-tenant boundaries).
- **Offers** are displayed by `best_offer_display`, in cents, from the stored offers (ADR-0023).
- **The model only writes one intro line.** The items, prices, offers and reasons shown come from
  the rules and the stored data, in a card (ADR-0023).
- **Invalid input is rejected at the boundary:** negative prices, a percent outside 0 to 100, a
  duplicate item id and similar raise `ValueError` (the same style as `app.business.returns`).

## Consequences

- Pure functions over plain dataclasses, with unit tests, no database and no model; the data layer
  maps rows to them.
- A guardrail has to block any item or price in the reply that is not in the turn's cards, in the
  same way the output checks work today (ADR-0008). That is part of the agent wiring and is not
  built yet.
- Without co-purchase data the cross-sell depends on the complement tags the enrichment agent wrote
  (ADR-0024), so its quality follows theirs.

## Alternatives considered

- **Let the model pick what to offer next:** rejected, it invents items and prices and cannot be
  tested.
- **Only co-purchase counts:** rejected, a new shop has no orders; tags work from day one and counts
  take over when they exist.
