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
| [0006](0006-llm-driven-knowledge-base-search.md) | Knowledge-base search is the one tool the LLM calls itself | Accepted |
| [0007](0007-input-safety-cascade.md) | Input safety is a three-tier cascade | Accepted |
| [0008](0008-deterministic-output-guardrails.md) | Output guardrails are deterministic checks against state | Accepted |
| [0009](0009-stateless-chat-api.md) | The chat API is stateless; the client resends the conversation | Accepted |
| [0010](0010-stream-then-correct.md) | Stream tokens live, and correct afterwards if a guardrail rewrites the answer | Accepted |
| [0011](0011-self-hosted-langfuse-for-tracing.md) | Self-hosted Langfuse for tracing, instead of LangSmith | Accepted |
| [0012](0012-evaluation-against-the-real-api.md) | Evaluate the running API with a dev set, a held-out set and mostly deterministic metrics | Accepted |

For the system and agent-graph diagrams, see [`docs/architecture.md`](../architecture.md).

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
