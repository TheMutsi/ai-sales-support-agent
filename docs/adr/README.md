# Architecture Decision Records

Each record captures one decision that shaped this codebase: the context that forced
it, what was decided, and what it costs. They are written so the reasoning survives
after the conversation that produced it, and so a reviewer can disagree with a
specific trade-off instead of reverse-engineering it from the code.

Records describe decisions that are implemented on `main`. When a decision is
replaced, the old record stays, marked `Superseded by ADR-NNNN`, and the new one
links back to it.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-langgraph-with-typed-state-and-deterministic-routing.md) | LangGraph with an explicit typed state; the LLM classifies, Python routes | Accepted |
| [0002](0002-deterministic-business-rules-layer.md) | Business facts come from a deterministic rules layer, never from the LLM | Accepted |
| [0003](0003-layering-and-dependency-direction.md) | Layering and dependency direction between packages | Accepted |
| [0004](0004-provider-agnostic-llm-and-embeddings.md) | Provider-agnostic chat models and embeddings behind factories | Accepted |
| [0005](0005-postgres-pgvector-for-rag.md) | Postgres + pgvector as the only datastore, with per-doc-type chunking | Accepted |

## Writing a new one

Copy the template below into `NNNN-short-title.md` with the next free number, and
add it to the index in the same PR as the change it describes.

```markdown
# ADR-NNNN: Title as a decision, not a topic

- **Status:** Proposed | Accepted | Superseded by ADR-NNNN
- **Introduced in:** PR or stage

## Context
What forced a decision: the constraint, the failure, the requirement.

## Decision
What was decided, specific enough to check against the code.

## Consequences
What gets easier, what gets harder, and what is now a known limitation.

## Alternatives
Options that were rejected, and why.

## References
Code paths and PRs.
```
