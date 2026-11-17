import os

import pytest

from app.core import observability
from app.core.config import Settings

LANGFUSE_KEYS = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]


@pytest.fixture(autouse=True)
def _restore_environ():
    original = {key: os.environ.get(key) for key in LANGFUSE_KEYS}
    yield
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_pushes_settings_into_environ(monkeypatch):
    monkeypatch.setattr(
        observability,
        "get_settings",
        lambda: Settings(
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
            langfuse_host="http://localhost:3000",
        ),
    )

    observability.configure_langfuse()

    assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-lf-test"
    assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-lf-test"
    assert os.environ["LANGFUSE_HOST"] == "http://localhost:3000"
