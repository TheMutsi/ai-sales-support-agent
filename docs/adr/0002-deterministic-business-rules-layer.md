# ADR-0002: Business facts come from a deterministic rules layer, never from the LLM

- **Status:** Accepted
- **Introduced in:** Stage 4 (business rules), Stage 5 (tools); plan catalog in PR #52

## Context

The agent sells as well as supports: it may suggest an upgrade, quote a price, or
create a checkout. A model asked "should this customer upgrade?" will produce a
plausible answer whether or not it is true, and it will happily upsell a customer
whose payment already failed. These are facts the database can answer exactly, and
getting them wrong is a business problem, not a style problem.

## Decision

All commercial decisions live in `app/business/` as pure functions over ORM rows,
with no LLM, no I/O and no framework imports:

- `eligibility.check_upgrade_eligibility`: a `canceled` or `past_due` subscription
  cannot upgrade (offering a pricier plan to a customer whose payment failed makes
  things worse).
- `upsell_rules.evaluate_upsell`: a three-step decision tree (already included? on
  any plan? eligible?) that always returns a `reason`, on the negative path too, so
  the agent can give a specific answer instead of a bare no.
- `pricing.calculate_upgrade_price`: the plain price delta, no proration. The
  simulated billing has no mid-cycle invoicing state, so a prorated number would be
  invented precision.

`app/tools/` wraps these with database access, and enforces the invariants that must
hold no matter who calls them: `create_upgrade_checkout` re-checks eligibility itself
and raises `UpgradeNotEligibleError` rather than trusting the caller to have checked.

In the graph, the LLM only writes text around these results:

- `business_rules_node` calls the eligibility tool and puts the `EligibilityResult`
  in state.
- For `pricing_question`, `get_plan_catalog` loads every plan from the `plans` table
  before the answer is written, with prices already formatted in dollars, so neither
  the figure nor the cents-to-dollars arithmetic is left to the model. The knowledge
  base deliberately carries no prices, so they cannot drift from the table (PR #52).
- Refunds have no tool at all, so `refund_request` always escalates to a human.

## Consequences

- The rules are tested exhaustively and fast (TDD, no mocks of the model).
- The guardrails can check the model's text against state (ADR-0008): a checkout link
  with no `checkout_session`, or a refund confirmation, is provably false.
- The rules only know what the schema models. Anything outside it (proration,
  discounts, partial refunds) gets escalated, not approximated.
- `create_upgrade_checkout` and `evaluate_upsell` exist and are tested, but no graph
  node calls them yet: the upgrade path today stops at the eligibility answer. Wiring
  them in is a graph change, not a rules change.

## Alternatives

- **Rules in the prompt** ("only offer an upgrade if the subscription is active").
  Untestable, and a small model follows it inconsistently.
- **Let the LLM call the eligibility tool when it sees fit.** The check would then be
  optional; making it structural is the point.

## References

- `backend/app/business/`, `backend/app/tools/upsell.py`, `backend/app/tools/errors.py`
- `backend/app/agent/nodes/business_rules.py`, `plan_catalog.py`, `backend/app/tools/plans.py`
