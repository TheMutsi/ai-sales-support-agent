from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root, not backend/ — this file lives at backend/app/core/config.py, and the
# .env file is checked out one level above `backend/`. Resolved from this file's own
# path (not the process cwd) so `.env` loads the same way whether you run `pytest`
# from `backend/`, the app from the repo root, or Docker (which doesn't use this at
# all — it injects .env as real process env vars via docker-compose's `env_file`).
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"

    # Port 5433: the docker-compose `db` service maps to 5433 on the host to avoid
    # colliding with a native Postgres install that may already own 5432.
    database_url: str = "postgresql+psycopg://acmeflow:acmeflow@localhost:5433/acmeflow"

    llm_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    google_api_key: str | None = None
    google_model: str = "gemini-2.5-pro"
    # Free local option, no API key: requires `ollama pull qwen2.5:7b-instruct` and
    # `ollama serve` running on the host — see CLAUDE.md.
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_base_url: str = "http://localhost:11434"

    embedding_provider: str = "google"
    embedding_model: str = "text-embedding-004"
    # Ollama's nomic-embed-text outputs 768-dim vectors — matches EMBEDDING_DIM in
    # app/db/models.py, verified against a real local call, not assumed.
    ollama_embedding_model: str = "nomic-embed-text"

    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "acmeflow-agent"


@lru_cache
def get_settings() -> Settings:
    return Settings()
