from langchain_core.messages import SystemMessage

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.business.escalation import EscalationRoute
from app.core.llm import get_chat_model
from app.schemas.agent import Intent
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    RetentionChoice,
    RetentionReceipt,
)
from app.schemas.tools import EscalationReceipt, PlanSummary

_RAG_ELIGIBLE_INTENTS = {
    Intent.PRODUCT_QUESTION,
    Intent.PRICING_QUESTION,
    Intent.TECHNICAL_SUPPORT,
    Intent.BILLING_QUESTION,
}

_SEARCH_REQUIRED_INTENTS = {
    Intent.PRODUCT_QUESTION,
    Intent.TECHNICAL_SUPPORT,
}
_NEVER_SHOWN_TO_CUSTOMERS = {"customer_id", "email"}
_SEARCH_REQUIRED_REMINDER = (
    "You have not searched the knowledge base in this turn and the context has no "
    "MewFlow facts. Call the search tool now instead of replying."
)


def _build_context_blob(state: AgentState) -> str:
    sections: list[str] = []

    if customer_context := state.get("customer_context"):
        account = customer_context.model_dump_json(indent=2, exclude=_NEVER_SHOWN_TO_CUSTOMERS)
        sections.append(f"Customer account:\n{account}")

    if eligibility_result := state.get("eligibility_result"):
        sections.append(f"Upgrade eligibility:\n{eligibility_result.model_dump_json(indent=2)}")

    if upsell_decision := state.get("upsell_decision"):
        sections.append(f"Upsell recommendation:\n{upsell_decision.model_dump_json(indent=2)}")

    if plan_catalog := state.get("plan_catalog"):
        sections.append(f"Plan catalog (list prices):\n{_format_plan_catalog(plan_catalog)}")

    if order := state.get("order_details"):
        sections.append(f"Order:\n{_format_order(order)}")
    elif (orders := state.get("customer_orders")) is not None:
        listing = "\n".join(_format_order(o) for o in orders) or "This customer has no orders."
        sections.append(f"The customer's orders:\n{listing}")
    elif state.get("intent") == Intent.ORDER_STATUS:
        sections.append("Order:\nThere is no order with that number for this customer.")

    if hints := _format_hints(state):
        sections.append(f"What the visitor's browser told us (unverified):\n{hints}")

    if checkout_session := state.get("checkout_session"):
        sections.append(f"Checkout created:\n{checkout_session.model_dump_json(indent=2)}")

    if receipt := state.get("escalation_receipt"):
        sections.append(f"Escalated to a person:\n{_format_escalation(receipt)}")

    return (
        "\n\n".join(sections) if sections else "No additional data was retrieved for this request."
    )


def _format_escalation(receipt: EscalationReceipt) -> str:
    follow_up = (
        "An agent will join this chat when one is free; the customer can keep writing here."
        if receipt.route is EscalationRoute.LIVE
        else "Nobody can join the chat now: a person will follow up later. The reference is "
        "how the customer (or the team) finds this conversation again."
    )
    return f"Follow-up number: {receipt.reference}\n{follow_up}"


def _format_plan_catalog(plans: list[PlanSummary]) -> str:
    def limit(value: int | None) -> str:
        return "unlimited" if value is None else str(value)

    return "\n".join(
        f"- {plan.name}: ${plan.price_cents / 100:,.2f}, billed {plan.billing_period}"
        f"; seats: {limit(plan.seat_limit)}; API calls per month: {limit(plan.api_call_limit)}"
        f"; features: {', '.join(plan.features)}"
        for plan in plans
    )


def _format_hints(state: AgentState) -> str:
    properties = state.get("conversation_properties") or {}
    lines = [f"- {key}: {value}" for key, value in properties.items()]
    if tags := state.get("conversation_tags"):
        lines.append(f"- tags: {', '.join(tags)}")
    return "\n".join(lines)


_STATUS_TEXT = {
    OrderStatus.OPEN: "open (not shipped yet)",
    OrderStatus.IN_DELIVERY: "in delivery (on its way)",
}


def _status_text(status: OrderStatus) -> str:
    return _STATUS_TEXT.get(status, status.value)


def _format_order(order: OrderDetails) -> str:
    line = (
        f"- {order.item_name or order.plan_slug.capitalize() + ' plan'} order: "
        f"${order.amount_cents / 100:,.2f} {order.currency}, status {_status_text(order.status)}, "
        f"placed {order.created_at:%Y-%m-%d}"
    )
    if (kept := order.retention) is not None:
        line += f"; kept by the customer with {_retention_text(kept)}"
    return line


def _retention_text(receipt: RetentionReceipt) -> str:
    if receipt.choice is RetentionChoice.REFUND:
        return f"a refund of ${(receipt.refund_cents or 0) / 100:,.2f} to their card"
    return f"${(receipt.credit_cents or 0) / 100:,.2f} in credits added to their account"


def response_writer_node(state: AgentState) -> dict:
    context = _build_context_blob(state)
    system_message = SystemMessage(content=RESPONSE_WRITER_SYSTEM_PROMPT.format(context=context))

    llm = get_chat_model()
    if state.get("intent") in _RAG_ELIGIBLE_INTENTS:
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
