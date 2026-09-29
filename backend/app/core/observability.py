"""LangSmith tracing setup.

LangChain's tracer reads LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY / LANGCHAIN_PROJECT
directly from the process environment via its own global callback handler — it never
sees our typed `Settings` object. `Settings` loads `.env` into itself only, so without
this function those variables would sit unused in `.env` and tracing would silently
stay off. `configure_langsmith()` is the one place that pushes them into `os.environ`,
called once at app startup, so every later `.invoke()` on a chain/model/graph is traced
with no further wiring in agent/tool code.
"""

import os

from app.core.config import get_settings


def configure_langsmith() -> None:
    settings = get_settings()

    os.environ["LANGCHAIN_TRACING_V2"] = "true" if settings.langchain_tracing_v2 else "false"
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project

    if settings.langchain_api_key:
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
