from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.schemas.agent import Intent, ReturnChoice
from app.schemas.business import EligibilityResult, UpsellDecision
from app.schemas.cards import CardAction
from app.schemas.orders import OrderDetails, PendingReturn, ReturnResult
from app.schemas.tools import CheckoutSession, CustomerContext, EscalationReceipt, PlanSummary


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

    customer_id: str | None
    conversation_properties: dict[str, str]
    conversation_tags: list[str]
    tenant_id: str | None
    order_id: str | None
    scopes: list[str]
    scope_overrides: dict | None
    identity_required: bool
    identity_methods: list[str]
    input_blocked: bool
    intent: Intent | None
    intent_confidence: float | None
    safety_confidence: float | None

    customer_context: CustomerContext | None
    plan_catalog: list[PlanSummary] | None
    order_details: OrderDetails | None
    customer_orders: list[OrderDetails] | None
    pending_return: PendingReturn | None
    action: CardAction | None
    action_order_id: str | None
    return_result: ReturnResult | None
    return_reading: ReturnChoice | None

    eligibility_result: EligibilityResult | None
    upsell_decision: UpsellDecision | None

    checkout_session: CheckoutSession | None
    escalation_receipt: EscalationReceipt | None
    open_escalation: EscalationReceipt | None

    escalated: bool
    escalation_reason: str | None

    errors: list[str]
    guardrail_flags: Annotated[list[str], add]

    tool_call_rounds: int
