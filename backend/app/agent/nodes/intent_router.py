from langchain_core.messages import BaseMessage, SystemMessage

from app.agent.prompts.intent_router import INTENT_ROUTER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.agent import Intent, IntentClassification

# A greeting, thank-you or goodbye is short and asks nothing. The 7B model sometimes
# files an off-topic request as small_talk, which would skip the ticket and the
# second safety look `unsupported` gets, so the label is only trusted for this shape.
_SMALL_TALK_MAX_WORDS = 10


def _looks_like_small_talk(message: BaseMessage) -> bool:
    text = str(message.content)
    return "?" not in text and len(text.split()) <= _SMALL_TALK_MAX_WORDS


def intent_router(state: AgentState) -> dict:
    # Ollama's smaller local models occasionally emit invalid structured output
    # (e.g. `"confidence": Infinity`) that fails Pydantic validation — retry the
    # whole call rather than reusing the broken response.
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
