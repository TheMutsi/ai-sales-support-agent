from langchain_core.messages import SystemMessage

from app.agent.prompts.intent_router import INTENT_ROUTER_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.agent import IntentClassification


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

    return {"intent": result.intent, "intent_confidence": result.confidence}
