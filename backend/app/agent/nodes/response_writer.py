from langchain_core.messages import SystemMessage

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.agent import Intent
from app.schemas.tools import PlanSummary

# The intents where response_writer binds the knowledge-base tool. Billing is
# included because general billing questions (payment methods, cancellation,
# proration) are answered by the KB's billing documents, and without the tool
# the model has nothing to ground them on and invents answers. The tool is
# read-only, so account facts still come only from get_customer_context.
# Refund, upgrade and escalation stay grounded only in what their own nodes
# put in state.
_RAG_ELIGIBLE_INTENTS = {
    Intent.PRODUCT_QUESTION,
    Intent.PRICING_QUESTION,
    Intent.TECHNICAL_SUPPORT,
    Intent.BILLING_QUESTION,
}

# These two reach response_writer with nothing gathered by earlier nodes, so
# a first reply that doesn't search can only be ungrounded or empty. The eval
# suite caught qwen2.5 doing both about half the time on a direct probe
# (empty message, or "let me search" with no tool call). Billing and pricing
# are left out: they arrive with the customer context or the plan catalog.
_SEARCH_REQUIRED_INTENTS = {
    Intent.PRODUCT_QUESTION,
    Intent.TECHNICAL_SUPPORT,
}
# Appended to the system prompt for the single retry, the portable equivalent
# of `tool_choice="required"`, which Ollama does not support.
_SEARCH_REQUIRED_REMINDER = (
    "You have not searched the knowledge base in this turn and the context has no "
    "AcmeFlow facts. Call the search tool now instead of replying."
)


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

    if plan_catalog := state.get("plan_catalog"):
        sections.append(f"Plan catalog (list prices):\n{_format_plan_catalog(plan_catalog)}")

    if checkout_session := state.get("checkout_session"):
        sections.append(f"Checkout created:\n{checkout_session.model_dump_json(indent=2)}")

    if ticket_receipt := state.get("ticket_receipt"):
        sections.append(f"Support ticket created:\n{ticket_receipt.model_dump_json(indent=2)}")

    return (
        "\n\n".join(sections) if sections else "No additional data was retrieved for this request."
    )


def _format_plan_catalog(plans: list[PlanSummary]) -> str:
    """Prices pre-formatted in dollars: converting cents is arithmetic, and
    arithmetic is not left to the model."""

    def limit(value: int | None) -> str:
        return "unlimited" if value is None else str(value)

    return "\n".join(
        f"- {plan.name}: ${plan.price_cents / 100:,.2f}, billed {plan.billing_period}"
        f"; seats: {limit(plan.seat_limit)}; API calls per month: {limit(plan.api_call_limit)}"
        f"; features: {', '.join(plan.features)}"
        for plan in plans
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

    if (
        state.get("intent") in _SEARCH_REQUIRED_INTENTS
        and state.get("tool_call_rounds", 0) == 0
        and not ai_message.tool_calls
    ):
        reminder = SystemMessage(content=f"{system_message.content}\n\n{_SEARCH_REQUIRED_REMINDER}")
        ai_message = llm.invoke([reminder, *state["messages"]])

    return {"messages": [ai_message]}
