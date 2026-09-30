"""Unit test for the intent_router node, with the chat model mocked out.

Per CLAUDE.md's testing philosophy, graph nodes are tested against a stubbed
LLM response, asserting on deterministic state transitions — not on real
model output, which belongs to the evaluation suite instead.
"""

from langchain_core.messages import HumanMessage

from app.agent.nodes import intent_router as intent_router_module
from app.schemas.agent import Intent, IntentClassification


class _FakeStructuredChatModel:
    """Stands in for `get_chat_model()`'s return value. Mimics only the chain
    `intent_router` actually calls — `.with_structured_output(...)` and
    `.with_retry(...)` both just return self, and `.invoke(...)` hands back a
    fixed response instead of calling a real model."""

    def __init__(self, response: IntentClassification):
        self._response = response

    def with_structured_output(self, schema):
        return self

    def with_retry(self, **kwargs):
        return self

    def invoke(self, messages):
        return self._response


def test_returns_the_classified_intent_and_confidence(monkeypatch):
    fake_response = IntentClassification(
        intent=Intent.PRICING_QUESTION, confidence=0.87, reasoning="Asks about plan cost."
    )
    monkeypatch.setattr(
        intent_router_module,
        "get_chat_model",
        lambda: _FakeStructuredChatModel(fake_response),
    )

    state = {"messages": [HumanMessage(content="cuanto sale el plan pro?")]}
    result = intent_router_module.intent_router(state)

    assert result == {"intent": Intent.PRICING_QUESTION, "intent_confidence": 0.87}
