from langchain_core.messages import AIMessage

from app.agent.permissions import REQUIRED_SCOPE, identity_methods_for
from app.agent.state import AgentState

ASK_TO_VERIFY = "To help with that I need to verify it's you. Please use the form below."
ASK_TO_LOG_IN = "To help with that, please log in to your account first."
ASK_FOR_THE_ORDER = (
    "To check an order I need its number, and I can't ask for it here. "
    "Please contact support so they can help you with it."
)


def request_identity_node(state: AgentState) -> dict:
    scope = REQUIRED_SCOPE[state["intent"]]
    methods = identity_methods_for(scope, state.get("scope_overrides"))
    already_has_scope = scope in (state.get("scopes") or [])
    if already_has_scope:
        only_the_order_is_missing = [method for method in methods if method == "order_id"]
        methods = only_the_order_is_missing
    if methods:
        text = ASK_TO_VERIFY
    elif already_has_scope:
        text = ASK_FOR_THE_ORDER
    else:
        text = ASK_TO_LOG_IN
    return {
        "identity_required": True,
        "identity_methods": methods,
        "messages": [AIMessage(content=text)],
    }
