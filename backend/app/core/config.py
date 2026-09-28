from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"

    database_url: str = "postgresql+psycopg://acmeflow:acmeflow@localhost:5432/acmeflow"

    llm_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    google_api_key: str | None = None
    google_model: str = "gemini-2.5-pro"

    embedding_provider: str = "google"
    embedding_model: str = "text-embedding-004"

    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "acmeflow-agent"


@lru_cache
def get_settings() -> Settings:
    return Settings()
