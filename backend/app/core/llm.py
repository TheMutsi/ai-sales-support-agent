from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from app.core.config import LLMProvider, get_settings


@lru_cache
def get_chat_model() -> BaseChatModel:
    settings = get_settings()
    return create_chat_model(settings.llm_provider, get_chat_model_name())


def create_chat_model(provider: LLMProvider, model: str) -> BaseChatModel:
    settings = get_settings()

    if provider == "anthropic":
        return ChatAnthropic(model=model, anthropic_api_key=settings.anthropic_api_key)

    if provider == "google":
        return ChatGoogleGenerativeAI(model=model, google_api_key=settings.google_api_key)

    if provider == "ollama":
        return ChatOllama(model=model, base_url=settings.ollama_base_url)

    raise ValueError(f"Unsupported LLM provider: {provider!r}")


def get_chat_model_name() -> str:
    settings = get_settings()

    if settings.llm_provider == "anthropic":
        return settings.anthropic_model
    if settings.llm_provider == "google":
        return settings.google_model
    if settings.llm_provider == "ollama":
        return settings.ollama_model

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider!r}")
