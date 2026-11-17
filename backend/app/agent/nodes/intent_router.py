from langchain_core.messages import BaseMessage, SystemMessage

from app.agent.prompts.intent_router import INTENT_ROUTER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.agent import Intent, IntentClassification

_SMALL_TALK_MAX_WORDS = 10


def _looks_like_small_talk(message: BaseMessage) -> bool:
    text = str(message.content)
    return "?" not in text and len(text.split()) <= _SMALL_TALK_MAX_WORDS


def intent_router(state: AgentState) -> dict:
    structured_llm = (
        get_chat_model()
        .with_structured_output(IntentClassification)
        .with_retry(stop_after_attempt=3)
    )

    messages = [SystemMessage(content=INTENT_ROUTER_SYSTEM_PROMPT), *state["messages"]]
    result = structured_llm.invoke(messages)

    intent = result.intent
    if intent == Intent.SMALL_TALK and not _looks_like_small_talk(state["messages"][-1]):
        intent = Intent.UNSUPPORTED

    return {
        "intent": intent,
        "intent_confidence": result.confidence,
        "safety_confidence": result.safety_confidence,
    }
