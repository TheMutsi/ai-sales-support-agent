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
    return create_chat_model(settings.llm_provider, get_chat_model_name())


def create_chat_model(provider: str, model: str) -> BaseChatModel:
    """Builds a chat model for an explicit provider/model pair. The app always
    goes through `get_chat_model()`; this exists for callers that need a model
    other than the configured one, e.g. the evaluation suite's judge, which
    should not be the same model as the agent it grades."""
    settings = get_settings()

    if provider == "anthropic":
        return ChatAnthropic(model=model, anthropic_api_key=settings.anthropic_api_key)

    if provider == "google":
        return ChatGoogleGenerativeAI(model=model, google_api_key=settings.google_api_key)

    if provider == "ollama":
        return ChatOllama(model=model, base_url=settings.ollama_base_url)

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")


def get_chat_model_name() -> str:
    """The model id for whichever provider `LLM_PROVIDER` currently selects —
    used to tag LangSmith traces (Stage 8) with what actually answered a
    conversation, without duplicating the provider if/elif here."""
    settings = get_settings()

    if settings.llm_provider == "anthropic":
        return settings.anthropic_model
    if settings.llm_provider == "google":
        return settings.google_model
    if settings.llm_provider == "ollama":
        return settings.ollama_model

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}")
