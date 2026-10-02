from langchain_core.messages import SystemMessage

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.agent import Intent

# The only intents where response_writer binds the knowledge-base tool —
# everything else (billing/refund/upgrade/escalation) stays fully
# deterministic, grounded only in what get_customer_context/business_rules/
# human_escalation already put in state.
_RAG_ELIGIBLE_INTENTS = {Intent.PRODUCT_QUESTION, Intent.PRICING_QUESTION, Intent.TECHNICAL_SUPPORT}


def _build_context_blob(state: AgentState) -> str:
    """Serializes whatever earlier nodes gathered into text the LLM can ground
    on — only the fields a given run actually populated are included, so the
    prompt doesn't dangle empty sections for paths that never touched them."""
    sections: list[str] = []

    if customer_context := state.get("customer_context"):
        sections.append(f"Customer account:\n{customer_context.model_dump_json(indent=2)}")

    if eligibility_result := state.get("eligibility_result"):
        sections.append(f"Upgrade eligibility:\n{eligibility_result.model_dump_json(indent=2)}")

    if upsell_decision := state.get("upsell_decision"):
        sections.append(f"Upsell recommendation:\n{upsell_decision.model_dump_json(indent=2)}")

    if checkout_session := state.get("checkout_session"):
        sections.append(f"Checkout created:\n{checkout_session.model_dump_json(indent=2)}")

    if ticket_receipt := state.get("ticket_receipt"):
        sections.append(f"Support ticket created:\n{ticket_receipt.model_dump_json(indent=2)}")

    return (
        "\n\n".join(sections) if sections else "No additional data was retrieved for this request."
    )


def response_writer_node(state: AgentState) -> dict:
    context = _build_context_blob(state)
    system_message = SystemMessage(content=RESPONSE_WRITER_SYSTEM_PROMPT.format(context=context))

    llm = get_chat_model()
    if state.get("intent") in _RAG_ELIGIBLE_INTENTS:
        # bind_tools must come before with_retry: RunnableRetry (what
        # with_retry returns) has no bind_tools method of its own.
        llm = llm.bind_tools([make_search_knowledge_base_tool(state["customer_id"])])
    llm = llm.with_retry(stop_after_attempt=3)

    ai_message = llm.invoke([system_message, *state["messages"]])

    return {"messages": [ai_message]}
