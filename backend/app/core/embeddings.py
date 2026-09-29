"""Embeddings abstraction.

Two providers (see CLAUDE.md "Architecture"): Google's `text-embedding-004` (default),
and Ollama's `nomic-embed-text` for offline/no-API-key dev — both output 768-dim
vectors, matching `EMBEDDING_DIM = 768` in `app/db/models.py` (Stage 1). Factored as a
function, not inlined at the call site, so the RAG pipeline (Stage 3) never imports a
provider SDK directly.
"""

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_ollama import OllamaEmbeddings

from app.core.config import get_settings


@lru_cache
def get_embeddings() -> Embeddings:
    settings = get_settings()

    if settings.embedding_provider == "google":
        return GoogleGenerativeAIEmbeddings(
            model=f"models/{settings.embedding_model}",
            google_api_key=settings.google_api_key,
        )

    if settings.embedding_provider == "ollama":
        return OllamaEmbeddings(
            model=settings.ollama_embedding_model,
            base_url=settings.ollama_base_url,
        )

    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider!r}")
