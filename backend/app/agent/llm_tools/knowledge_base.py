import uuid

from langchain_core.tools import tool

from app.schemas.rag import SourceReference
from app.tools.knowledge_base import search_knowledge_base

SEARCH_KNOWLEDGE_BASE_DESCRIPTION = (
    "Search MewFlow's knowledge base (features, billing, policies, FAQ, "
    "security, integrations) with a natural-language query. Call this when "
    "you need a specific fact you don't already have from the conversation "
    "so far — don't call it for greetings or questions you can already "
    "answer."
)


def make_search_knowledge_base_tool(customer_id: uuid.UUID | None):
    @tool(response_format="content_and_artifact", description=SEARCH_KNOWLEDGE_BASE_DESCRIPTION)
    def search_knowledge_base_tool(query: str) -> tuple[str, list[SourceReference]]:
        chunks = search_knowledge_base(customer_id, query)
        if not chunks:
            return "No relevant knowledge base results found.", []
        one_citation_per_document = {
            chunk.document_id: SourceReference(
                title=chunk.document_title, doc_type=chunk.doc_type, source=chunk.source
            )
            for chunk in chunks
        }
        return "\n---\n".join(chunk.content for chunk in chunks), list(one_citation_per_document.values())

    return search_knowledge_base_tool
