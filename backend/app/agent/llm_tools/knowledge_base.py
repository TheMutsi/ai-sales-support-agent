"""LangChain `@tool`-wrapped binding for `app.tools.knowledge_base`, exposed
to the agent's LLM calls.

Kept separate from `app/tools/` on purpose: those are plain, framework-
agnostic functions a graph node calls directly (the Dependency Rule — they
don't need to know LangChain exists). Deciding which of them the LLM itself
is allowed to invoke, and under what schema, is an agent-orchestration
concern, not a tools-layer one — it belongs here, next to the nodes that
bind it, same as `app/agent/nodes/` and `app/agent/prompts/` keep one file
per concept instead of growing a single catch-all module.
"""

import uuid

from langchain_core.tools import tool

from app.tools.knowledge_base import search_knowledge_base


def make_search_knowledge_base_tool(customer_id: uuid.UUID):
    """Builds a `search_knowledge_base` tool closed over `customer_id`. The
    LLM must never be able to choose whose plan scope a search applies to —
    it only ever sees `query`, never the customer identity — so
    `customer_id` comes from the graph's own state at bind time, not from an
    argument the model fills in.

    The retriever's `doc_type` filter is deliberately not exposed either. The
    evaluation suite found the model guessing the category wrong (SSO under
    `integrations`, API limits under `billing`), and the filter then excluded
    the one document holding the answer. Unfiltered, the right chunk ranked
    first for every one of those queries, so the model gets no filter to
    misuse."""

    @tool
    def search_knowledge_base_tool(query: str) -> str:
        """Search AcmeFlow's knowledge base (features, billing, policies, FAQ,
        security, integrations) with a natural-language query. Call this when
        you need a specific fact you don't already have from the conversation
        so far — don't call it for greetings or questions you can already
        answer."""
        chunks = search_knowledge_base(customer_id, query)
        if not chunks:
            return "No relevant knowledge base results found."
        return "\n---\n".join(chunk.content for chunk in chunks)

    return search_knowledge_base_tool
