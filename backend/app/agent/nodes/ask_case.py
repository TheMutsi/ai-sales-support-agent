from langchain_core.messages import AIMessage

from app.agent.pushback import CASE_QUESTION
from app.agent.state import AgentState


def ask_case_node(state: AgentState) -> dict:
    """First request for a person: ask what happened before opening a ticket. Fixed text, no model,
    so `asked_for_case` can recognize it next turn."""
    return {"messages": [AIMessage(content=CASE_QUESTION)]}
