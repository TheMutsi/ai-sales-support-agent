"""Langfuse tracing setup — self-hosted (see `docker-compose.yml`'s
`langfuse-*` services), not LangSmith's cloud. Self-hosting LangSmith turned
out to be an Enterprise-only, paid add-on rather than something runnable
locally for free, which is why this project traces through Langfuse instead
(open source, MIT-licensed backend, real Docker Compose deployment).

Langfuse's `get_client()` / `CallbackHandler()` read LANGFUSE_PUBLIC_KEY /
LANGFUSE_SECRET_KEY / LANGFUSE_HOST directly from the process environment —
they never see our typed `Settings` object. `Settings` loads `.env` into
itself only, so without this function those variables would sit unused and
tracing would silently stay off. `configure_langfuse()` is the one place
that pushes them into `os.environ`, called once at app startup.
"""

import os

from app.core.config import get_settings


def configure_langfuse() -> None:
    settings = get_settings()

    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = settings.langfuse_host
