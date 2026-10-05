"""Unit tests for the LLM provider factory.

These only assert on which concrete class `get_chat_model()` returns for a given
`LLM_PROVIDER` — constructing a LangChain chat model client makes no network call,
so no real API key or network access is needed here.
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from pydantic import ValidationError

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


def test_settings_reject_an_unsupported_provider():
    with pytest.raises(ValidationError, match="llm_provider"):
        Settings(llm_provider="openai")


def test_create_chat_model_uses_the_requested_model(monkeypatch):
    """The eval judge builds a model other than the configured one."""
    monkeypatch.setattr(llm, "get_settings", lambda: Settings(llm_provider="ollama"))

    model = llm.create_chat_model("ollama", "llama3")

    assert isinstance(model, ChatOllama)
    assert model.model == "llama3"


def test_create_chat_model_raises_on_an_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        llm.create_chat_model("openai", "gpt")
