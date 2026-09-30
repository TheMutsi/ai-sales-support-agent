"""Second-tier safety check — only reached when `intent_router`'s own
`safety_confidence` came back below the threshold in `app/agent/routing.py`.

This is the expensive path: a dedicated LLM call with a prompt focused only
on this one decision, instead of the cheap confidence score `intent_router`
already produces in its single classification call. Most conversations never
reach this node at all, which is the point of the cascade — pay for a closer
look only when the cheap signal is genuinely unsure, not on every message.
"""

import logging

from langchain_core.messages import AIMessage, SystemMessage

from app.agent.nodes.input_guardrail import REFUSAL_MESSAGE
from app.agent.prompts.safety_judge import SAFETY_JUDGE_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.core.llm import get_chat_model
from app.schemas.guardrails import SafetyJudgment

logger = logging.getLogger(__name__)


def safety_judge_node(state: AgentState) -> dict:
    structured_llm = (
        get_chat_model().with_structured_output(SafetyJudgment).with_retry(stop_after_attempt=3)
    )

    messages = [SystemMessage(content=SAFETY_JUDGE_SYSTEM_PROMPT), *state["messages"]]
    result = structured_llm.invoke(messages)

    if result.is_safe:
        return {}

    logger.warning("safety_judge blocked a message: %s", result.reasoning)

    return {
        "input_blocked": True,
        "guardrail_flags": ["semantic_unsafe_message"],
        "messages": [AIMessage(content=REFUSAL_MESSAGE)],
    }
