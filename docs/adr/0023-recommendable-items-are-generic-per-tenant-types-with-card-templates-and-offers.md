# ADR-0023: Recommendable items are generic: per-tenant types with card templates and offers

- **Status:** Accepted (the catalog tables, the offer rules and the card are built and tested; the admin API, the back office page and the agent wiring are not)
- **Introduced in:** the generic recommendation feature (catalog data layer, offer rules, recommendation card)

## Context

Each tenant sells different things: products, articles, services. The assistant has to recommend
them, but the code and the prompts must not hardcode one shop's catalog (the demo data happens to
be skincare; that lives only in the seed files). The widget also cannot accept markup from a
tenant, so a tenant cannot design its own card.

## Decision

- **A per-tenant type defines the fields of an item and picks a card template** from a fixed set
  the widget owns (`product_card` first). A type has a key, a name, a template and a JSON field
  schema. Items (`recommendation_items`) belong to a type and carry price in cents, currency,
  rating, image, link, free `extra` JSON, a `status` (`draft`, `active`, `archived`), an
  `enrichment_status` (see ADR-0024) and an embedding with a full-text vector for fallback search.
- **Offers** (`item_offers`: `pack`, `discount`, `bundle`) are stored per item and **priced by
  Python** (`app.business.offers.best_offer_display`: price, struck-through price and discount
  percent, in cents). The model never states a price.
- **Packs of one product are separate items sharing a `product_id`**, each with a `pack_size`, so
  an upsell is "the bigger pack of the same product" and a search result can show either.
- **The database enforces tenancy.** Child tables carry `tenant_id` in a composite foreign key
  (`item_tags`, `item_offers`, items to types), so a link across tenants is rejected by Postgres
  and not only by application code. CHECK constraints reject negative prices, quantity 0 and
  `pack_size` 0.
- **The card is a typed message part** (`RecommendationCard` with a `RecommendationTemplate`),
  built from cents on the server. The card's link must be absolute http(s) and its image http(s)
  or a relative path, enforced in the schema and again when the widget renders it. Unknown cards or
  templates are dropped when a conversation is read, like any card the code no longer knows.

## Consequences

- A tenant with a new kind of item adds a type and its fields, not code. A new template is a widget
  change and a release, on purpose: tenants cannot ship markup.
- Several new tables and one migration (`a3d9c1f27b64`), and the seed now creates rows that point at
  tenants, so test helpers that wipe tables by hand delete the catalog tables first.
- A discount offer is stored as `price_cents` plus `compare_at_cents`; there is no percent column.
  A discount without `compare_at_cents` cannot be priced and has to be handled where rows are mapped
  to the rules (the search task).
- Rows are mapped to the rules' `Candidate` by a small adapter (kind `discount` becomes percent,
  items with price 0 such as articles are filtered by type). The tier of a price is derived with
  `price_tier` from per-tenant boundaries, not stored.

## Alternatives considered

- **Hardcoded product fields and one card:** rejected, it ties the chat to one shop.
- **Tenant-defined HTML or templates:** rejected, markup from a tenant in a shopper's page is an
  injection path.
- **Prices written by the model from retrieved text:** rejected, a price is a fact a function can
  compute (ADR-0002, ADR-0018).
