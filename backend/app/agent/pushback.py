from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage

CASE_QUESTION = (
    "Of course, I can pass you to a person. Before that, could you tell me what happened? "
    "I may be able to solve it right now. If you'd rather talk to someone, just ask again."
)


_RECENT_MESSAGES = 8


def asked_for_case(messages: Sequence[BaseMessage]) -> bool:
    recent = messages[-_RECENT_MESSAGES:]
    return any(isinstance(m, AIMessage) and m.content == CASE_QUESTION for m in recent)


def last_reply_in(messages: Sequence[BaseMessage], replies: frozenset[str]) -> bool:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return isinstance(message.content, str) and message.content in replies
    return False
