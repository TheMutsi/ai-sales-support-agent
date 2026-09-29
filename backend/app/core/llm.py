"""LLM provider abstraction.

Everything outside this module — agent nodes, tools, business logic — must call
`get_chat_model()` instead of importing `ChatAnthropic` / `ChatGoogleGenerativeAI`
directly. That's the entire abstraction: swapping providers is an `LLM_PROVIDER`
env var change, never a code change in the modules that use the model.
"""

from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from app.core.config import get_settings


@lru_cache
def get_chat_model() -> BaseChatModel:
    settings = get_settings()

    if settings.llm_provider == "anthropic":
        return ChatAnthropic(
            model=settings.anthropic_model,
            anthropic_api_key=settings.anthropic_api_key,
        )

    if settings.llm_provider == "google":
        return ChatGoogleGenerativeAI(
            model=settings.google_model,
            google_api_key=settings.google_api_key,
        )

    if settings.llm_provider == "ollama":
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
        )

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}")
