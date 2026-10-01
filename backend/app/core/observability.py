"""LangSmith tracing setup.

LangChain's tracer reads LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY / LANGCHAIN_PROJECT
directly from the process environment via its own global callback handler — it never
sees our typed `Settings` object. `Settings` loads `.env` into itself only, so without
this function those variables would sit unused in `.env` and tracing would silently
stay off. `configure_langsmith()` is the one place that pushes them into `os.environ`,
called once at app startup, so every later `.invoke()` on a chain/model/graph is traced
with no further wiring in agent/tool code.
"""

import logging
import os
import uuid

from langsmith import Client

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def configure_langsmith() -> None:
    settings = get_settings()

    os.environ["LANGCHAIN_TRACING_V2"] = "true" if settings.langchain_tracing_v2 else "false"
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project

    if settings.langchain_api_key:
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key


def tag_run_intent(run_id: uuid.UUID, intent: str) -> None:
    """Patches `intent` onto an already-started LangSmith trace once
    `intent_router` has classified it. The chat endpoint tags everything else
    (customer_id, conversation_id, environment, model, app_version) through
    `config={"metadata": ...}` at invoke time, but `intent` isn't known until
    partway through the graph run — this is the only way to still make traces
    filterable by it in the LangSmith UI.

    Reads the run before writing: `update_run`'s `extra` replaces the whole
    field rather than deep-merging it, so writing `{"metadata": {"intent": ...}}`
    directly would silently drop the metadata set at invoke time.

    Best-effort by design — tracing is observability, not something allowed to
    break a chat response, so any failure here (tracing disabled, LangSmith
    unreachable) is logged and swallowed rather than raised to the caller."""
    settings = get_settings()
    if not settings.langchain_tracing_v2:
        return

    try:
        client = Client()
        run = client.read_run(run_id)
        metadata = dict((run.extra or {}).get("metadata") or {})
        metadata["intent"] = intent
        client.update_run(run_id, extra={**(run.extra or {}), "metadata": metadata})
    except Exception:
        logger.warning("Failed to tag intent onto LangSmith run %s", run_id, exc_info=True)
