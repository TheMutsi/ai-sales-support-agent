# ADR-0003: Layering and dependency direction between packages

- **Status:** Accepted
- **Introduced in:** Stages 4-7; the guardrails cycle was removed in PR #48

## Context

LangChain makes it easy for every module to import a framework type, and an agent
codebase drifts towards everything importing everything. That makes the
deterministic parts (rules, tools, guardrails) hard to test in isolation and hard to
reuse outside the graph, for example from the evaluation suite.

## Decision

Dependencies point one way, from the edges towards the contracts:

```
api ──► agent ──► tools ──► business ──► db ──► core
          │         └────► rag ──► db, core
          ├──► guardrails
          └──► core (llm, embeddings, config)

every package above ──► schemas      (schemas imports nothing from app)
evaluation ──► app.schemas, app.core, app.db, and /api/chat over HTTP
```

This is the import graph on `main`, checked package by package, not an aspiration.

- **`app/schemas/` is the shared vocabulary.** Pydantic contracts that more than one
  layer reads (`Intent`, `CustomerContext`, `ChatTurnSummary`,
  `OutputCheckContext`) live here and import nothing from the other packages.
- **`app/tools/` and `app/business/` are framework-agnostic.** Plain typed functions;
  no LangChain import. Which of them the LLM may call, and with what schema, is an
  agent decision, so the `@tool` binding lives in `app/agent/llm_tools/`.
- **`app/guardrails/` depends only on `app/schemas/`.** Output checks take an
  `OutputCheckContext` (five facts about the turn) instead of `AgentState`, and the
  prompt to protect is passed in. `guardrail_node` builds that context from state.
- **`evaluation` depends on `app`, never the reverse.** It drives the agent only
  through `/api/chat`, reuses the `done` event contract (`ChatTurnSummary`) so the
  endpoint and its client cannot drift apart, and imports `core` (to build the judge
  model) and `db` (to resolve dataset customers by email).

## Consequences

- Rules, tools and guardrails are pure-ish functions tested without the graph.
- Before PR #48, `guardrails` imported `AgentState` and the response-writer prompt
  from `agent`, while `agent` imported `guardrails`: a package cycle. The contract
  type removed it, at the cost of one small mapping function.
- Tools open their own DB session (`SessionLocal`), because `AgentState` has no place
  for a live session between nodes. The RAG retriever, one level lower, takes the
  session as an argument instead.
- The direction is a convention, not enforced by a lint rule. A reviewer has to catch
  a violation.

## Alternatives

- **Guardrails reading `AgentState` directly.** Less code, but it couples the checks
  to the graph's internal shape and created the cycle above.
- **`@tool` decorators on `app/tools/` functions.** Saves a file, but every tool
  would depend on LangChain and become LLM-callable by default.

## References

- `backend/app/schemas/`, `backend/app/agent/llm_tools/knowledge_base.py`
- `backend/app/guardrails/output_checks.py`, `backend/app/agent/nodes/guardrail.py`
