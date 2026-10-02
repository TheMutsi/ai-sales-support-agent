from langchain_core.messages import SystemMessage

from app.agent.prompts.human_escalation import HUMAN_ESCALATION_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.agent import Intent, TicketDraft
from app.schemas.tools import TicketCategory
from app.tools.tickets import create_support_ticket

# Deterministic lookup, no LLM call needed since `intent` is already
# classified by this point in the graph.
_INTENT_TICKET_CATEGORY = {
    Intent.REFUND_REQUEST: TicketCategory.REFUND,
    Intent.TECHNICAL_SUPPORT: TicketCategory.TECHNICAL,
    Intent.BILLING_QUESTION: TicketCategory.BILLING,
    Intent.HUMAN_ESCALATION: TicketCategory.ESCALATION,
}


def human_escalation_node(state: AgentState) -> dict:
    intent = state["intent"]
    category = _INTENT_TICKET_CATEGORY.get(intent, TicketCategory.OTHER)

    structured_llm = (
        get_chat_model().with_structured_output(TicketDraft).with_retry(stop_after_attempt=3)
    )
    draft = structured_llm.invoke(
        [SystemMessage(content=HUMAN_ESCALATION_SYSTEM_PROMPT), *state["messages"]]
    )

    ticket = create_support_ticket(
        customer_id=state["customer_id"],
        category=category,
        subject=draft.subject,
        description=draft.description,
    )
    return {"ticket_receipt": ticket, "escalated": True}
