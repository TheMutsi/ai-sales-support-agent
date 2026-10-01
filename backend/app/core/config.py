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

    # Self-hosted Langfuse (see `docker-compose.yml`'s `langfuse-*` services) —
    # not LangSmith: self-hosting LangSmith is an Enterprise-only, paid add-on,
    # not something you can run locally for free. Public/secret key defaults
    # here match the local-dev-only bootstrap values `docker-compose.yml`
    # seeds the Langfuse project with, so tracing works out of the box with no
    # manual key-copying — they're meaningless outside this local stack.
    langfuse_tracing_enabled: bool = False
    langfuse_public_key: str = "pk-lf-acmeflow-local"
    langfuse_secret_key: str = "sk-lf-acmeflow-local-dev-only"
    langfuse_host: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
