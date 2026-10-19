from langchain_core.messages import SystemMessage

from app.agent.llm_tools.knowledge_base import make_search_knowledge_base_tool
from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.agent import Intent
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    RetentionChoice,
    RetentionReceipt,
    ReturnOutcome,
    ReturnResult,
)
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
    "MewFlow facts. Call the search tool now instead of replying."
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

    if order := state.get("order_details"):
        sections.append(f"Order:\n{_format_order(order)}")
    elif return_result := state.get("return_result"):
        sections.append(f"Order return:\n{_format_return(return_result)}")
    elif (orders := state.get("customer_orders")) is not None:
        listing = "\n".join(_format_order(o) for o in orders) or "This customer has no orders."
        sections.append(f"The customer's orders:\n{listing}")
    elif state.get("intent") == Intent.ORDER_STATUS:
        sections.append("Order:\nThere is no order with that number for this customer.")

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


_STATUS_TEXT = {
    OrderStatus.OPEN: "open (not shipped yet)",
    OrderStatus.IN_DELIVERY: "in delivery (on its way)",
}


def _status_text(status: OrderStatus) -> str:
    return _STATUS_TEXT.get(status, status.value)


def _format_order(order: OrderDetails) -> str:
    """The amount in dollars, like the plan catalog: converting cents is not left to the model."""
    line = (
        f"- Order {order.order_id}: plan {order.plan_slug}, "
        f"${order.amount_cents / 100:,.2f} {order.currency}, status {_status_text(order.status)}, "
        f"placed {order.created_at:%Y-%m-%d}"
    )
    if (kept := order.retention) is not None:
        line += f"; kept by the customer with {_retention_text(kept)}"
    return line


def _retention_text(receipt: RetentionReceipt) -> str:
    if receipt.choice is RetentionChoice.REFUND:
        return f"a refund of ${(receipt.refund_cents or 0) / 100:,.2f} to their card"
    if receipt.choice is RetentionChoice.NEXT_ORDER_FREE:
        return f"their next order free (coupon {receipt.coupon_code})"
    return f"{receipt.credit_points or 0:,} points added to their account"


def _format_return(result: ReturnResult) -> str:
    """What the return step did, in words the writer repeats. Amounts are worked out here."""
    order = result.order
    what = (
        f"order {order.order_id} (${order.amount_cents / 100:,.2f}, status {_status_text(order.status)})"
        if order
        else "the order"
    )
    match result.outcome:
        case ReturnOutcome.NOTHING_TO_RETURN:
            return (
                "The customer has no order that can be rejected or returned (an order that "
                "was kept with an offer, is closed, paid or delivered cannot). Nothing was changed. Say so, "
                "do not ask for an order number, and offer to bring in a person if they need more."
            )
        case ReturnOutcome.CHOOSE_ORDER:
            return (
                "Ask which of these orders the customer wants to reject or return. Nothing "
                f"was changed.\n{chr(10).join(_format_order(o) for o in result.candidates)}"
            )
        case ReturnOutcome.OFFER:
            offer = result.offer
            assert order is not None and offer is not None
            on_its_way = (
                " It is on its way, so it cannot be rejected now: if they decline the offer, "
                "they can return it once it arrives."
                if order.status is OrderStatus.IN_DELIVERY
                else " If they decline the offer they can still reject it."
            )
            return (
                f"The customer wants to reject {what}. Before that, offer them to keep it "
                f"for one of two things: (1) ${offer.refund_cents / 100:,.2f} back to their "
                f"card, (2) {offer.credit_points:,} points in their account, or (3) their next "
                f"order free.{on_its_way} "
                "Nothing has been done yet: ask which they prefer, and say nothing else about "
                "charges or payments."
            )
        case ReturnOutcome.CONFIRM_CANCEL:
            return (
                f"{what} has not shipped, so it can be cancelled. Nothing has been done yet. Only "
                "ask the customer to confirm that they want to cancel it (for example \"Do you "
                "want me to cancel it?\"). Do not say it will be cancelled, and say nothing "
                "about charges, payments or refunds."
            )
        case ReturnOutcome.RETURN_LATER:
            return (
                f"{what} is on its way, so it cannot be rejected now. The customer can return it "
                "once it arrives. Nothing was changed. Tell them only that, and ask whether they need "
                "anything else: do not offer refunds, points or any other option, and do not ask "
                "whether they want to return it now."
            )
        case ReturnOutcome.CANCELLED:
            return f"{what} HAS BEEN cancelled: tell them so in the past tense."
        case (
            ReturnOutcome.KEPT_WITH_REFUND
            | ReturnOutcome.KEPT_WITH_CREDITS
            | ReturnOutcome.KEPT_WITH_FREE_ORDER
        ):
            assert result.receipt is not None
            return (
                f"The customer kept {what} and took {_retention_text(result.receipt)}. That has "
                "ALREADY BEEN DONE: tell them so in the past tense (for example \"I've added "
                "2,100 points to your account\", \"I've refunded $14.00 to your card\" or \"Your next "
                "order is free, use the coupon code\"). The "
                "order stays with them: it is not cancelled and does not need to be returned."
            )
        case ReturnOutcome.KEPT_AS_IS:
            return f"The customer keeps {what} as it is. Nothing was changed."
        case ReturnOutcome.NOT_AVAILABLE:
            return (
                f"{what} can no longer be changed this way, so nothing was changed. Say so, "
                "and offer to bring in a person if they need more."
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
