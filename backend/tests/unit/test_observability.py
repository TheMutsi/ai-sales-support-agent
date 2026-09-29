"""Unit tests for LangSmith env-var wiring.

`configure_langsmith()` mutates `os.environ`, a process-wide global, so this suite
restores whatever was there before each test instead of just deleting keys — it must
not leak env state into whichever test, in this file or another, runs after it.
"""

import os

import pytest

from app.core import observability
from app.core.config import Settings

TRACING_KEYS = ["LANGCHAIN_TRACING_V2", "LANGCHAIN_PROJECT", "LANGCHAIN_API_KEY"]


@pytest.fixture(autouse=True)
def _restore_environ():
    original = {key: os.environ.get(key) for key in TRACING_KEYS}
    yield
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_sets_tracing_env_vars_when_enabled(monkeypatch):
    monkeypatch.setattr(
        observability,
        "get_settings",
        lambda: Settings(
            langchain_tracing_v2=True,
            langchain_project="acmeflow-agent",
            langchain_api_key="test-key",
        ),
    )

    observability.configure_langsmith()

    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_PROJECT"] == "acmeflow-agent"
    assert os.environ["LANGCHAIN_API_KEY"] == "test-key"


def test_sets_tracing_v2_false_when_disabled(monkeypatch):
    monkeypatch.setattr(
        observability,
        "get_settings",
        lambda: Settings(langchain_tracing_v2=False, langchain_project="acmeflow-agent"),
    )

    observability.configure_langsmith()

    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_does_not_set_api_key_when_not_configured(monkeypatch):
    os.environ.pop("LANGCHAIN_API_KEY", None)
    monkeypatch.setattr(
        observability,
        "get_settings",
        lambda: Settings(
            langchain_tracing_v2=False,
            langchain_project="acmeflow-agent",
            langchain_api_key=None,
        ),
    )

    observability.configure_langsmith()

    assert "LANGCHAIN_API_KEY" not in os.environ
