"""Unit tests for `get_chat_model_name()` — the LangSmith trace-metadata helper
added in Stage 8. No network call: it only reads `Settings`, same as
`get_chat_model()`'s own provider branch in `test_llm.py`."""

import pytest

from app.core import llm
from app.core.config import Settings


def test_returns_anthropic_model_for_anthropic_provider(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(llm_provider="anthropic", anthropic_model="claude-sonnet-5"),
    )

    assert llm.get_chat_model_name() == "claude-sonnet-5"


def test_returns_google_model_for_google_provider(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(llm_provider="google", google_model="gemini-2.5-pro"),
    )

    assert llm.get_chat_model_name() == "gemini-2.5-pro"


def test_returns_ollama_model_for_ollama_provider(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(llm_provider="ollama", ollama_model="qwen2.5:7b-instruct"),
    )

    assert llm.get_chat_model_name() == "qwen2.5:7b-instruct"


def test_raises_on_unsupported_provider(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: Settings(llm_provider="openai"))

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        llm.get_chat_model_name()
