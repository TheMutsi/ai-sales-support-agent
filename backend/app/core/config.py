from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


LLMProvider = Literal["anthropic", "google", "ollama"]


_DEV_SESSION_KEY = "dev-only-session-signing-key-change-me"
_DEV_ENCRYPTION_KEY = "QfxUoq4U_nd0a17NgubcRMPK2uxUNiGw0KzvtDQrXe4="
LOCAL_ENVIRONMENTS = {"development", "local", "test"}
_MIN_SESSION_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"

    database_url: str = Field(
        default="postgresql+psycopg://mewflow:mewflow@localhost:5433/mewflow",
        description="Host port 5433, so the compose database never collides with a native 5432.",
    )
    cors_allow_origins: list[str] = Field(
        default=["http://localhost:5173"],
        description="An explicit allow-list, never '*'. Set it as a JSON list.",
    )
    session_signing_key: str = Field(
        default=_DEV_SESSION_KEY, description="Signs our sessions; refused outside local envs."
    )
    audit_hmac_key: str = Field(
        default="",
        description=(
            "Keys the audit hashes apart from the session key, so rotating or leaking that one "
            "leaves them intact. Empty means the session key, in local environments only."
        ),
    )
    secrets_encryption_key: str = Field(
        default=_DEV_ENCRYPTION_KEY,
        description="Fernet key for credentials stored in the database; never kept there.",
    )
    session_ttl_seconds: int = 24 * 3600
    tenant_config_ttl_seconds: int = Field(
        default=60, description="How long tenant configuration may be served from memory."
    )
    admin_api_enabled: bool = Field(
        default=False,
        description="Opt-in, and only honoured in a local environment (`admin_api_is_mounted`).",
    )
    trusted_proxy_count: int = Field(
        default=0, description="Proxies appending to X-Forwarded-For; 0 ignores the header."
    )

    llm_provider: LLMProvider = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    google_api_key: str | None = None
    google_model: str = "gemini-2.5-pro"
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_base_url: str = "http://localhost:11434"
    ollama_num_ctx: int = Field(
        default=16384,
        gt=0,
        description="Ollama's context window in tokens; without it Ollama truncates silently.",
    )

    embedding_provider: str = "google"
    embedding_model: str = "text-embedding-004"
    ollama_embedding_model: str = "nomic-embed-text"

    langfuse_tracing_enabled: bool = False
    langfuse_public_key: str = "pk-lf-mewflow-local"
    langfuse_secret_key: str = "sk-lf-mewflow-local-dev-only"
    langfuse_host: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _require_real_session_key(self) -> "Settings":
        key = self.session_signing_key
        if key == _DEV_SESSION_KEY and self.app_env not in LOCAL_ENVIRONMENTS:
            raise ValueError("SESSION_SIGNING_KEY must be set to a real secret outside local envs.")
        if len(key) < _MIN_SESSION_KEY_LENGTH:
            raise ValueError(
                f"SESSION_SIGNING_KEY must be at least {_MIN_SESSION_KEY_LENGTH} characters."
            )
        return self

    @model_validator(mode="after")
    def _require_a_real_audit_key(self) -> "Settings":
        key = self.audit_hmac_key
        if not key:
            if self.app_env not in LOCAL_ENVIRONMENTS:
                raise ValueError("AUDIT_HMAC_KEY must be set to a real secret outside local envs.")
            return self
        if len(key) < _MIN_SESSION_KEY_LENGTH:
            raise ValueError(f"AUDIT_HMAC_KEY must be at least {_MIN_SESSION_KEY_LENGTH} characters.")
        if key == self.session_signing_key:
            raise ValueError("AUDIT_HMAC_KEY must differ from SESSION_SIGNING_KEY.")
        return self

    @model_validator(mode="after")
    def _require_a_real_encryption_key(self) -> "Settings":
        key = self.secrets_encryption_key
        if key == _DEV_ENCRYPTION_KEY and self.app_env not in LOCAL_ENVIRONMENTS:
            raise ValueError("SECRETS_ENCRYPTION_KEY must be set to a real key outside local envs.")
        try:
            Fernet(key)
        except ValueError as problem:
            raise ValueError("SECRETS_ENCRYPTION_KEY must be a Fernet key (32 url-safe base64 bytes).") from problem
        return self

    @property
    def admin_api_is_mounted(self) -> bool:
        return self.admin_api_enabled and self.app_env in LOCAL_ENVIRONMENTS

    @property
    def audit_key(self) -> str:
        return self.audit_hmac_key or self.session_signing_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
