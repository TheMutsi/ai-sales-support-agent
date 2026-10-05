# ADR-0006: Knowledge-base search is the one tool the LLM calls itself

- **Status:** Accepted
- **Introduced in:** PR #27; `doc_type` filter removed in PR #42; search retry in PR #49

## Context

In Stage 6 the graph always ran retrieval before answering a product, pricing or
technical question (a `retrieve_knowledge` node). That retrieved for greetings and
follow-ups that needed nothing, and it searched with the raw user message (rather
than a focused query) under a `doc_type` filter fixed per intent. Knowledge-base
search is also the one action with no business risk: it is read-only and returns
public product documentation.

## Decision

- For `product_question`, `pricing_question`, `technical_support` and
  `billing_question`, `response_writer` binds a `search_knowledge_base_tool` and the
  model decides whether and what to search. The prefetch node was removed.
- **The model only supplies `query`.** `customer_id` (which scopes plan-specific
  documents) is closed over from graph state when the tool is built, so the model
  can never search on behalf of another customer.
- **The `doc_type` filter is not exposed to the model.** The evaluation suite showed
  it guessing the category wrong (SSO under `integrations`, API limits under
  `billing`), and the filter then excluded the one document holding the answer.
  Unfiltered, the right chunk ranked first for every one of those queries.
- **The loop is bounded**: at most `_MAX_TOOL_CALL_ROUNDS` (2) search rounds per
  turn, enforced by routing.
- **Bad arguments are the model's mistake, not a crash.** A `ValidationError` goes
  back to the model as an error `ToolMessage` it can correct; database or embedding
  failures still propagate.
- Every other intent has no tool bound, so refund, upgrade and escalation stay fully
  deterministic (ADR-0002).
- Billing is in the list because general billing questions (payment methods,
  cancellation) are answered by KB documents; without the tool the model invented
  answers. Account facts still come only from `get_customer_context`.
- Pricing keeps the tool for policy questions (discounts, quotes), but the prices
  themselves are loaded deterministically from the plans table first (ADR-0002).
- **Product and technical questions get one retry if the model skips the search.**
  They reach `response_writer` with no gathered context, so a reply without a search
  can only be ungrounded or empty. The retry appends a reminder to the system prompt:
  the portable equivalent of `tool_choice="required"`, which Ollama does not support.

## Consequences

- Fewer pointless retrievals, and queries the model rewrites to be searchable.
- The model can also decide not to search when it should. On product and technical
  questions `qwen2.5:7b-instruct` skipped it (empty reply, or "let me search" with no
  call) in about half of direct probes; with the retry, the search ran 16 of 16 times
  (PR #49). Billing is not retried, since it arrives with the customer context, and
  the evaluation suite still records billing answers given without a search.
- Tool names and call syntax can leak into the answer text; an output check blocks
  that (ADR-0008).
- Exposing a parameter to the model is now a decision that needs evidence: the
  `doc_type` lesson was that a filter the model can misuse costs more than it saves.

## Alternatives

- **Keep the deterministic prefetch.** Predictable, but retrieves on every turn with
  an unrewritten query.
- **Force a tool call on every turn** (`tool_choice`). Not portable across the three
  providers, and wrong for greetings and follow-ups.
- **Expose all tools to the model.** Rejected by ADR-0001 and ADR-0002.

## References

- `backend/app/agent/llm_tools/knowledge_base.py`
- `backend/app/agent/nodes/response_writer.py`, `knowledge_tool.py`, `routing.py`
