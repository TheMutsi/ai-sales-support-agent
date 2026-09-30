from langchain_core.messages import SystemMessage

from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model


def _build_context_blob(state: AgentState) -> str:
    """Serializes whatever earlier nodes gathered into text the LLM can ground
    on — only the fields a given run actually populated are included, so the
    prompt doesn't dangle empty sections for paths that never touched them."""
    sections: list[str] = []

    if customer_context := state.get("customer_context"):
        sections.append(f"Customer account:\n{customer_context.model_dump_json(indent=2)}")

    if retrieved_chunks := state.get("retrieved_chunks"):
        chunks_text = "\n---\n".join(chunk.content for chunk in retrieved_chunks)
        sections.append(f"Knowledge base results:\n{chunks_text}")

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

    llm = get_chat_model().with_retry(stop_after_attempt=3)
    ai_message = llm.invoke([system_message, *state["messages"]])

    return {"messages": [ai_message]}
