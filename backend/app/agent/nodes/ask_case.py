from langchain_core.messages import AIMessage

from app.agent.pushback import CASE_QUESTION
from app.agent.state import AgentState


def ask_case_node(state: AgentState) -> dict:
    return {"messages": [AIMessage(content=CASE_QUESTION)]}
