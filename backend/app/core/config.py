from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root, not backend/ — this file lives at backend/app/core/config.py, and the
# .env file is checked out one level above `backend/`. Resolved from this file's own
# path (not the process cwd) so `.env` loads the same way whether you run `pytest`
# from `backend/`, the app from the repo root, or Docker (which doesn't use this at
# all — it injects .env as real process env vars via docker-compose's `env_file`).
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


# The chat-model providers `app.core.llm` can build. A typo in LLM_PROVIDER
# fails when settings load, not on the first chat request.
LLMProvider = Literal["anthropic", "google", "ollama"]


_DEV_SESSION_KEY = "dev-only-session-signing-key-change-me"
# The only environments allowed to run on the (public) development key. An
# allowlist rather than `!= "production"`: an environment named "prod" or
# "staging" must not fall through to a key anyone can read in the repo.
LOCAL_ENVIRONMENTS = {"development", "local", "test"}
_MIN_SESSION_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"

    # Port 5433: the docker-compose `db` service maps to 5433 on the host to avoid
    # colliding with a native Postgres install that may already own 5432.
    database_url: str = "postgresql+psycopg://mewflow:mewflow@localhost:5433/mewflow"

    # Origins the browser frontend is served from (Vite dev server by default).
    # An explicit allow-list, never "*": the API will carry customer-scoped
    # data. Env override is a JSON list: CORS_ALLOW_ORIGINS='["https://app.example.com"]'.
    cors_allow_origins: list[str] = ["http://localhost:5173"]

    # Signs the sessions `POST /api/auth/login` issues. The default is a local-dev
    # convenience only; `_require_real_session_key` refuses it outside local envs.
    session_signing_key: str = _DEV_SESSION_KEY
    # Keys the email and order hashes of `identification_events`, so rotating the session key does
    # not change every hash and a leaked session key does not make them guessable. Empty means
    # "use the session key", allowed in local environments only.
    audit_hmac_key: str = ""
    session_ttl_seconds: int = 24 * 3600
    # How many reverse proxies sit in front of the API and append to X-Forwarded-For. 0 means
    # the header is ignored (anyone can send it) and the socket peer is the client.
    trusted_proxy_count: int = 0

    llm_provider: LLMProvider = "anthropic"
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

    @property
    def audit_key(self) -> str:
        return self.audit_hmac_key or self.session_signing_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
