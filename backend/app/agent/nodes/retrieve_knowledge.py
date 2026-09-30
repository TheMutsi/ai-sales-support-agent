from app.agent.state import AgentState
from app.schemas.agent import Intent
from app.schemas.rag import DocType
from app.tools.knowledge_base import search_knowledge_base

# Only the intents routed here have an obvious doc_type — narrowing the search
# to it measurably improves relevance over an unfiltered search across every
# KB category. Intents with no clear single category are left unmapped, which
# falls back to an unfiltered search via the `.get(...)` below.
_INTENT_DOC_TYPE = {
    Intent.PRODUCT_QUESTION: DocType.FEATURES,
    Intent.PRICING_QUESTION: DocType.BILLING,
    Intent.TECHNICAL_SUPPORT: DocType.FAQ,
}


def retrieve_knowledge_node(state: AgentState) -> dict:
    latest_message = state["messages"][-1].content
    doc_type = _INTENT_DOC_TYPE.get(state["intent"])
    chunks = search_knowledge_base(state["customer_id"], latest_message, doc_type=doc_type)
    return {"retrieved_chunks": chunks}
