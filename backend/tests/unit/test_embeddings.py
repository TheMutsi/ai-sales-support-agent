"""Unit tests for the embeddings factory.

Same isolation approach as test_llm.py: constructing GoogleGenerativeAIEmbeddings
makes no network call, so this only checks provider selection and error handling.
"""

import pytest
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_ollama import OllamaEmbeddings

from app.core import embeddings
from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clear_cache():
    embeddings.get_embeddings.cache_clear()
    yield
    embeddings.get_embeddings.cache_clear()


def test_returns_google_generative_ai_embeddings_for_google_provider(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: Settings(
            embedding_provider="google",
            embedding_model="text-embedding-004",
            google_api_key="test-key",
        ),
    )

    model = embeddings.get_embeddings()

    assert isinstance(model, GoogleGenerativeAIEmbeddings)
    assert model.model == "models/text-embedding-004"


def test_returns_ollama_embeddings_for_ollama_provider(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: Settings(
            embedding_provider="ollama",
            ollama_embedding_model="nomic-embed-text",
            ollama_base_url="http://localhost:11434",
        ),
    )

    model = embeddings.get_embeddings()

    assert isinstance(model, OllamaEmbeddings)


def test_raises_on_unsupported_embedding_provider(monkeypatch):
    monkeypatch.setattr(embeddings, "get_settings", lambda: Settings(embedding_provider="openai"))

    with pytest.raises(ValueError, match="Unsupported EMBEDDING_PROVIDER"):
        embeddings.get_embeddings()
