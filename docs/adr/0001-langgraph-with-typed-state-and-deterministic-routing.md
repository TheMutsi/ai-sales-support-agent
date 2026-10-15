# ADR-0001: LangGraph with an explicit typed state; the LLM classifies, Python routes

- **Status:** Accepted
- **Introduced in:** Stage 6 (agent graph)

## Context

The agent has to do very different things depending on the request: answer from the
knowledge base, look up a customer's account, decide whether an upgrade is allowed,
or hand the conversation to a human. Some of those paths must never be decided by a
model (whether a refund is possible, whether a checkout may be created). A single
ReAct-style loop, where the model picks tools freely, would put every one of those
decisions in the model's hands and make the control flow impossible to test without
a live LLM.

## Decision

The agent is a LangGraph `StateGraph` over an explicit `AgentState` `TypedDict`
(`app/agent/state.py`):

- **The LLM produces a classification, not a route.** `intent_router` returns a
  structured `IntentClassification` (intent, confidence, safety confidence). Plain
  Python functions in `app/agent/routing.py` turn that into the next node.
- **Each node returns only the keys it changes.** `messages` and `guardrail_flags`
  use reducers (append) because more than one node writes to them in a run; every
  other field is a plain overwrite, owned by exactly one node.
- **State fields reuse the Pydantic contracts** from `app/schemas/`
  (`CustomerContext`, `EligibilityResult`, `TicketReceipt`, ...), so the shapes the
  tools return are the shapes the graph carries.
- **Every path ends at `guardrail`**, except the two input-refusal exits (see
  ADR-0007), so output checks cannot be skipped by a new branch.
- **Loops are bounded in code.** The `response_writer` ↔ `knowledge_tool` loop stops
  after `_MAX_TOOL_CALL_ROUNDS` (2), a value a test can pin, instead of relying only
  on LangGraph's recursion limit.

## Consequences

- Routing is unit-testable with a stubbed LLM: tests assert which node ran and what
  state looks like, never what the model wrote.
- Adding an intent means adding an enum value, a branch in `_dispatch_by_intent`,
  and a test. That is more ceremony than adding a tool to a free-form agent, and it
  is intentional.
- A misclassified intent sends the request down the wrong path. That is visible
  (intent is in every trace and in the `done` event) and measured by the
  evaluation suite's `intent_accuracy`, but it is not self-correcting.
- The only place the model chooses an action is knowledge-base search, and that
  choice was made on purpose (ADR-0006).

## Alternatives

- **Prebuilt ReAct agent with every tool bound.** Fewer lines, but eligibility,
  refunds and escalation would become model decisions, contradicting ADR-0002.
- **Plain Python if/else without LangGraph.** Workable at this size, but loses
  per-node tracing, the event stream the SSE endpoint is built on (ADR-0010), and the
  explicit graph that makes the flow reviewable.

## References

- `backend/app/agent/graph.py`, `state.py`, `routing.py`
- `backend/app/schemas/agent.py` (`Intent`, `IntentClassification`)
- `docs/architecture.md` for the graph diagram
