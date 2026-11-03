"""When a customer insists, and when to hand them to a person.

Two rules, both decided from what the assistant already said in this conversation, never by the
model and without storing a counter (the fixed replies are the memory):

- Asked for a person: the first time, the assistant asks what happened, in case it can solve it.
  If the customer asks again, a ticket is opened.
- Told "no" by the rules (an order on its way cannot be cancelled): the reply is given once.
  If the customer pushes back on it, a ticket is opened instead of explaining it again.

The fixed texts are matched exactly, so changing one only means the next turn after a deploy starts
the count again.
"""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage

CASE_QUESTION = (
    "Of course, I can pass you to a person. Before that, could you tell me what happened? "
    "I may be able to solve it right now. If you'd rather talk to someone, just ask again."
)


# How far back the question still counts: a request for a person hours later, about something else,
# starts again with the question.
_RECENT_MESSAGES = 8


def asked_for_case(messages: Sequence[BaseMessage]) -> bool:
    """Whether the assistant recently asked what happened, so a second request for a person is
    taken as insisting."""
    recent = messages[-_RECENT_MESSAGES:]
    return any(isinstance(m, AIMessage) and m.content == CASE_QUESTION for m in recent)


def last_reply_in(messages: Sequence[BaseMessage], replies: frozenset[str]) -> bool:
    """Whether the assistant's latest reply is one of these fixed texts, so a message right after
    it pushes back on it (anything in between, an answer about something else, ends the streak)."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return isinstance(message.content, str) and message.content in replies
    return False
