"""Unit tests for `tag_run_intent()` — the best-effort LangSmith metadata
patch added in Stage 8 (see its docstring in `app/core/observability.py` for
why it reads the run before writing instead of overwriting `extra` outright).
"""

import uuid

from app.core import observability
from app.core.config import Settings


class _FakeRun:
    def __init__(self, extra):
        self.extra = extra


class _FakeClient:
    """Stands in for `langsmith.Client` — records what `update_run` was
    called with so tests can assert on the merge behavior without a real
    LangSmith project."""

    def __init__(self, existing_extra=None, raise_on="none"):
        self._existing_extra = existing_extra or {}
        self._raise_on = raise_on
        self.update_run_calls: list[dict] = []

    def read_run(self, run_id):
        if self._raise_on == "read_run":
            raise RuntimeError("LangSmith unreachable")
        return _FakeRun(self._existing_extra)

    def update_run(self, run_id, *, extra):
        if self._raise_on == "update_run":
            raise RuntimeError("LangSmith unreachable")
        self.update_run_calls.append({"run_id": run_id, "extra": extra})


def test_does_nothing_when_tracing_is_disabled(monkeypatch):
    monkeypatch.setattr(observability, "get_settings", lambda: Settings(langchain_tracing_v2=False))
    monkeypatch.setattr(
        observability,
        "Client",
        lambda: (_ for _ in ()).throw(AssertionError("Client should not be constructed")),
    )

    observability.tag_run_intent(uuid.uuid4(), "pricing_question")


def test_merges_intent_into_existing_metadata_without_dropping_it(monkeypatch):
    fake_client = _FakeClient(existing_extra={"metadata": {"customer_id": "abc"}, "other": 1})
    monkeypatch.setattr(observability, "get_settings", lambda: Settings(langchain_tracing_v2=True))
    monkeypatch.setattr(observability, "Client", lambda: fake_client)
    run_id = uuid.uuid4()

    observability.tag_run_intent(run_id, "pricing_question")

    assert len(fake_client.update_run_calls) == 1
    call = fake_client.update_run_calls[0]
    assert call["run_id"] == run_id
    assert call["extra"]["other"] == 1
    assert call["extra"]["metadata"] == {"customer_id": "abc", "intent": "pricing_question"}


def test_swallows_a_read_run_failure(monkeypatch):
    fake_client = _FakeClient(raise_on="read_run")
    monkeypatch.setattr(observability, "get_settings", lambda: Settings(langchain_tracing_v2=True))
    monkeypatch.setattr(observability, "Client", lambda: fake_client)

    observability.tag_run_intent(uuid.uuid4(), "pricing_question")  # must not raise


def test_swallows_an_update_run_failure(monkeypatch):
    fake_client = _FakeClient(raise_on="update_run")
    monkeypatch.setattr(observability, "get_settings", lambda: Settings(langchain_tracing_v2=True))
    monkeypatch.setattr(observability, "Client", lambda: fake_client)

    observability.tag_run_intent(uuid.uuid4(), "pricing_question")  # must not raise
