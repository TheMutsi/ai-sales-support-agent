import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.scopes import IdentityLevel
from app.auth.session import (
    SessionError,
    issue_session_token,
    verify_session_token,
)

KEY = "k" * 32


def test_session_token_carries_who_and_how_they_were_identified():
    tenant_id, customer_id = uuid.uuid4(), uuid.uuid4()

    token, expires_at = issue_session_token(
        tenant_id=tenant_id,
        customer_id=customer_id,
        level=IdentityLevel.STORE_LOGIN,
        signing_key=KEY,
        ttl=timedelta(hours=24),
    )

    claims = jwt.decode(token, KEY, algorithms=["HS256"])
    assert claims["tid"] == str(tenant_id)
    assert claims["cid"] == str(customer_id)
    assert claims["lvl"] == "store_login"
    assert claims["exp"] == int(expires_at.timestamp())


def test_session_lives_for_the_requested_ttl():
    before = datetime.now(UTC)

    _, expires_at = issue_session_token(
        tenant_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        level=IdentityLevel.OTP_LOGIN,
        signing_key=KEY,
        ttl=timedelta(hours=24),
    )

    assert timedelta(hours=23, minutes=59) < expires_at - before < timedelta(hours=24, minutes=1)


def test_session_is_not_valid_under_a_different_key():
    token, _ = issue_session_token(
        tenant_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        level=IdentityLevel.STORE_LOGIN,
        signing_key=KEY,
        ttl=timedelta(hours=1),
    )

    try:
        jwt.decode(token, "other" * 8, algorithms=["HS256"])
    except jwt.InvalidSignatureError:
        return
    raise AssertionError("session token verified under the wrong key")


def _issue(**overrides) -> str:
    args = {
        "tenant_id": uuid.uuid4(),
        "customer_id": uuid.uuid4(),
        "level": IdentityLevel.STORE_LOGIN,
        "signing_key": KEY,
        "ttl": timedelta(hours=1),
    } | overrides
    return issue_session_token(**args)[0]


def test_verify_returns_the_claims_that_were_issued():
    tenant_id, customer_id = uuid.uuid4(), uuid.uuid4()
    token = _issue(tenant_id=tenant_id, customer_id=customer_id, level=IdentityLevel.OTP_LOGIN)

    claims = verify_session_token(token, KEY)

    assert claims.tenant_id == tenant_id
    assert claims.customer_id == customer_id
    assert claims.level is IdentityLevel.OTP_LOGIN


def test_verify_distinguishes_an_expired_session_so_the_client_can_log_in_again():
    token = _issue(ttl=timedelta(seconds=-120))

    with pytest.raises(SessionError) as error:
        verify_session_token(token, KEY)

    assert error.value.code == "session_expired"


def test_verify_rejects_a_token_signed_with_another_key():
    with pytest.raises(SessionError) as error:
        verify_session_token(_issue(signing_key="x" * 32), KEY)

    assert error.value.code == "invalid_session"


def test_verify_rejects_alg_none():
    forged = jwt.encode(
        {"tid": str(uuid.uuid4()), "cid": str(uuid.uuid4()), "lvl": "store_login", "exp": 9**10},
        None,
        algorithm="none",
    )

    with pytest.raises(SessionError):
        verify_session_token(forged, KEY)


@pytest.mark.parametrize(
    "claims",
    [
        {"cid": str(uuid.uuid4()), "lvl": "store_login"},  # no tid
        {"tid": str(uuid.uuid4()), "lvl": "store_login"},  # no cid
        {"tid": str(uuid.uuid4()), "cid": str(uuid.uuid4())},  # no lvl
        {"tid": "nope", "cid": str(uuid.uuid4()), "lvl": "store_login"},  # not a uuid
        {"tid": str(uuid.uuid4()), "cid": str(uuid.uuid4()), "lvl": "root"},  # unknown level
    ],
)
def test_verify_rejects_a_signed_token_with_missing_or_malformed_claims(claims):
    token = jwt.encode({**claims, "exp": 9**10}, KEY, algorithm="HS256")

    with pytest.raises(SessionError) as error:
        verify_session_token(token, KEY)

    assert error.value.code == "invalid_session"


def test_verify_rejects_garbage():
    with pytest.raises(SessionError):
        verify_session_token("not-a-jwt", KEY)
