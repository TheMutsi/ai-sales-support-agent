import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.deps import require_session
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.core.config import get_settings


def _bearer(ttl: timedelta = timedelta(hours=1), key: str | None = None) -> str:
    token, _ = issue_session_token(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        level=IdentityLevel.STORE_LOGIN,
        signing_key=key or get_settings().session_signing_key,
        ttl=ttl,
    )
    return f"Bearer {token}"


def test_a_valid_bearer_token_yields_the_session():
    session = require_session(_bearer())

    assert session.level is IdentityLevel.STORE_LOGIN


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer  "])
def test_a_missing_or_non_bearer_header_is_missing_session(header):
    with pytest.raises(HTTPException) as error:
        require_session(header)

    assert error.value.status_code == 401
    assert error.value.detail == {"code": "missing_session"}
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def test_an_expired_session_is_reported_as_such():
    with pytest.raises(HTTPException) as error:
        require_session(_bearer(ttl=timedelta(seconds=-120)))

    assert error.value.status_code == 401
    assert error.value.detail == {"code": "session_expired"}


def test_a_session_signed_with_another_key_is_invalid():
    with pytest.raises(HTTPException) as error:
        require_session(_bearer(key="x" * 32))

    assert error.value.detail == {"code": "invalid_session"}
