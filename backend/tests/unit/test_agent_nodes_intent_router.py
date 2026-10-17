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
        intent=Intent.PRICING_QUESTION,
        confidence=0.87,
        reasoning="Asks about plan cost.",
        safety_confidence=0.98,
    )
    monkeypatch.setattr(
        intent_router_module,
        "get_chat_model",
        lambda: _FakeStructuredChatModel(fake_response),
    )

    state = {"messages": [HumanMessage(content="cuanto sale el plan pro?")]}
    result = intent_router_module.intent_router(state)

    assert result == {
        "intent": Intent.PRICING_QUESTION,
        "intent_confidence": 0.87,
        "safety_confidence": 0.98,
    }


def _classify_as_small_talk(monkeypatch, text: str) -> Intent:
    response = IntentClassification(
        intent=Intent.SMALL_TALK, confidence=0.9, reasoning="x", safety_confidence=1.0
    )
    monkeypatch.setattr(
        intent_router_module, "get_chat_model", lambda: _FakeStructuredChatModel(response)
    )
    return intent_router_module.intent_router({"messages": [HumanMessage(content=text)]})["intent"]


def test_a_short_closing_message_stays_small_talk(monkeypatch):
    assert _classify_as_small_talk(monkeypatch, "Thanks!") is Intent.SMALL_TALK
    assert _classify_as_small_talk(monkeypatch, "Thank you so much, that's all.") is (
        Intent.SMALL_TALK
    )


def test_small_talk_is_not_trusted_for_a_question_or_a_long_message(monkeypatch):
    """The 7B model sometimes calls an off-topic request small talk, which would skip the
    ticket and the safety re-check `unsupported` gets; a request is never just thanks."""
    question = "Can you recommend a good pizza place nearby?"
    assert _classify_as_small_talk(monkeypatch, question) is Intent.UNSUPPORTED
    long = "thanks " * 20
    assert _classify_as_small_talk(monkeypatch, long) is Intent.UNSUPPORTED
