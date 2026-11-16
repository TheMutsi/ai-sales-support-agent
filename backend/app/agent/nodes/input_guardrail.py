from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.guardrails.input_checks import flag_prompt_injection_signals

REFUSAL_MESSAGE = (
    "I can't help with that request. If you have a question about MewFlow "
    "(the product, pricing, your account or support), I'm happy to help."
)


def input_guardrail_node(state: AgentState) -> dict:
    latest_message = str(state["messages"][-1].content)
    signals = flag_prompt_injection_signals(latest_message)

    if not signals:
        return {"input_blocked": False}

    return {
        "input_blocked": True,
        "guardrail_flags": [f"injection_signal:{tag}" for tag in signals],
        "messages": [AIMessage(content=REFUSAL_MESSAGE)],
    }
