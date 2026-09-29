"""Unit tests for the LLM provider factory.

These only assert on which concrete class `get_chat_model()` returns for a given
`LLM_PROVIDER` — constructing a LangChain chat model client makes no network call,
so no real API key or network access is needed here.
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from app.core import llm
from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clear_cache():
    llm.get_chat_model.cache_clear()
    yield
    llm.get_chat_model.cache_clear()


def test_returns_chat_anthropic_for_anthropic_provider(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(
            llm_provider="anthropic",
            anthropic_api_key="test-key",
            anthropic_model="claude-sonnet-5",
        ),
    )

    model = llm.get_chat_model()

    assert isinstance(model, ChatAnthropic)


def test_returns_chat_google_generative_ai_for_google_provider(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(
            llm_provider="google",
            google_api_key="test-key",
            google_model="gemini-2.5-pro",
        ),
    )

    model = llm.get_chat_model()

    assert isinstance(model, ChatGoogleGenerativeAI)


def test_returns_chat_ollama_for_ollama_provider(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(
            llm_provider="ollama",
            ollama_model="qwen2.5:7b-instruct",
            ollama_base_url="http://localhost:11434",
        ),
    )

    model = llm.get_chat_model()

    assert isinstance(model, ChatOllama)


def test_raises_on_unsupported_provider(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: Settings(llm_provider="openai"))

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        llm.get_chat_model()
