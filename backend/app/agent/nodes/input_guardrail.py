"""Runs first, before `intent_router` — a deterministic pre-filter, not an
LLM judgment call.

A regex match is weaker evidence than a tool result, so this is intentionally
narrow: only the attack shapes `app/guardrails/input_checks.py` curated
(instruction override, system-prompt extraction, code execution, DB
manipulation, roleplay jailbreak), not generic suspicious wording. When one
matches, the conversation never reaches `intent_router` at all — the LLM
never sees the payload, so there's nothing for a cleverer phrasing of the
same attack to talk it into. That's strictly stronger than asking the model
to refuse what it's already looking at, which is what the rest of the graph
still relies on for anything this pre-filter doesn't catch (see CLAUDE.md's
guardrails section on why detection stays narrow instead of trying to be
exhaustive).
"""

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.guardrails.input_checks import flag_prompt_injection_signals

_REFUSAL_MESSAGE = (
    "No puedo ayudarte con esa solicitud. Si tenés una consulta sobre AcmeFlow "
    "(producto, precios, tu cuenta o soporte), contame y te ayudo con gusto."
)


def input_guardrail_node(state: AgentState) -> dict:
    latest_message = str(state["messages"][-1].content)
    signals = flag_prompt_injection_signals(latest_message)

    if not signals:
        return {"input_blocked": False}

    return {
        "input_blocked": True,
        "guardrail_flags": [f"injection_signal:{tag}" for tag in signals],
        "messages": [AIMessage(content=_REFUSAL_MESSAGE)],
    }
