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


def request_identity_node(state: AgentState) -> dict:
    scope = REQUIRED_SCOPE[state["intent"]]
    methods = identity_methods_for(scope, state.get("scope_overrides"))
    if scope in (state.get("scopes") or []):
        # They already hold the scope (a customer verified with a code) and what is missing is
        # the order itself, so a second code would not help: offer only the order form.
        methods = [method for method in methods if method == "order_id"]
    text = ASK_TO_VERIFY if methods else ASK_TO_LOG_IN
    return {
        "identity_required": True,
        "identity_methods": methods,
        "messages": [AIMessage(content=text)],
    }
