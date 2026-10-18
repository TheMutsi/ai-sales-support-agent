"""Asks the visitor to identify, with a fixed text. No LLM runs here.

The email and the code never travel through the chat: the widget shows a form for
`identity_methods` and calls the identity endpoints directly, so they stay out of the
model, the history and the traces. After identifying, the turn is resumed from the
visitor's own message (see `app.chat.turns`).
"""

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
    if scope in (state.get("scopes") or []):
        # They already hold the scope (a customer verified with a code) and what is missing is
        # the order itself, so a second code would not help: offer only the order form.
        methods = [method for method in methods if method == "order_id"]
    already_has_scope = scope in (state.get("scopes") or [])
    if methods:
        text = ASK_TO_VERIFY
    elif already_has_scope:
        # Logged in already, and the tenant left no way to name an order: "log in" would be
        # wrong, since they are.
        text = ASK_FOR_THE_ORDER
    else:
        text = ASK_TO_LOG_IN
    return {
        "identity_required": True,
        "identity_methods": methods,
        "messages": [AIMessage(content=text)],
    }
