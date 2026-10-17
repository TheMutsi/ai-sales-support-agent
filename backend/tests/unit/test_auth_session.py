import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token

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
