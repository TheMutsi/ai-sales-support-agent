"""Shared state for the LangGraph agent graph.

Each node returns only the keys it changes; LangGraph merges that partial
dict onto the accumulated state between steps. `messages` needs the
`add_messages` reducer so a turn appends to the conversation instead of
replacing it — every other field is a plain overwrite, since within a single
run only one node is ever responsible for setting it.

Field values reuse the Pydantic contracts from `app/schemas/` (`CustomerContext`,
`UpsellDecision`, ...) instead of redefining shapes the tools and business
layers already return.

`guardrail_flags` needs the same kind of reducer as `messages`, for the same
reason: more than one node can contribute to it in a single run
(`input_guardrail_node` tags/blocks prompt-injection signals, `guardrail_node`
tags output violations), so a plain overwrite would silently drop whichever
ran first.
"""

from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.schemas.agent import Intent
from app.schemas.business import EligibilityResult, UpsellDecision
from app.schemas.tools import CheckoutSession, CustomerContext, TicketReceipt


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

    customer_id: str | None
    input_blocked: bool
    intent: Intent | None
    intent_confidence: float | None
    safety_confidence: float | None

    customer_context: CustomerContext | None

    eligibility_result: EligibilityResult | None
    upsell_decision: UpsellDecision | None

    checkout_session: CheckoutSession | None
    ticket_receipt: TicketReceipt | None

    escalated: bool
    escalation_reason: str | None

    errors: list[str]
    guardrail_flags: Annotated[list[str], add]

    # How many LLM↔tool round trips `response_writer`/`knowledge_tool` have
    # done for this turn — `route_after_response_writer` uses it to cap the
    # loop instead of relying only on LangGraph's generic recursion limit.
    tool_call_rounds: int
