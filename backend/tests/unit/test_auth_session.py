import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.scopes import IdentityLevel
from app.auth.session import SessionError, issue_session_token, verify_session_token

KEY = "k" * 32


def _issue(**overrides) -> tuple[str, datetime]:
    args = {
        "tenant_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "customer_id": uuid.uuid4(),
        "level": IdentityLevel.STORE_LOGIN,
        "signing_key": KEY,
        "ttl": timedelta(hours=1),
    } | overrides
    return issue_session_token(**args)


def _forge(claims: dict) -> str:
    """A correctly signed token with arbitrary claims, to probe the verifier."""
    return jwt.encode({"exp": 9**10, **claims}, KEY, algorithm="HS256")


def test_session_token_carries_the_conversation_and_how_they_were_identified():
    tenant_id, conversation_id, customer_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    token, expires_at = _issue(
        tenant_id=tenant_id, conversation_id=conversation_id, customer_id=customer_id
    )

    claims = jwt.decode(token, KEY, algorithms=["HS256"])
    assert claims["tid"] == str(tenant_id)
    assert claims["conv"] == str(conversation_id)
    assert claims["cid"] == str(customer_id)
    assert claims["lvl"] == "store_login"
    assert claims["exp"] == int(expires_at.timestamp())


def test_an_anonymous_session_has_no_customer_claim():
    token, _ = _issue(customer_id=None, level=IdentityLevel.ANONYMOUS)

    assert "cid" not in jwt.decode(token, KEY, algorithms=["HS256"])


def test_session_lives_for_the_requested_ttl():
    before = datetime.now(UTC)

    _, expires_at = _issue(ttl=timedelta(hours=24))

    assert timedelta(hours=23, minutes=59) < expires_at - before < timedelta(hours=24, minutes=1)


def test_verify_returns_the_claims_that_were_issued():
    tenant_id, conversation_id, customer_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token, _ = _issue(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        customer_id=customer_id,
        level=IdentityLevel.OTP_LOGIN,
    )

    claims = verify_session_token(token, KEY)

    assert claims.tenant_id == tenant_id
    assert claims.conversation_id == conversation_id
    assert claims.customer_id == customer_id
    assert claims.level is IdentityLevel.OTP_LOGIN


def test_verify_accepts_an_anonymous_session_without_a_customer():
    token, _ = _issue(customer_id=None, level=IdentityLevel.ANONYMOUS)

    claims = verify_session_token(token, KEY)

    assert claims.customer_id is None and claims.level is IdentityLevel.ANONYMOUS


def test_verify_distinguishes_an_expired_session_so_the_client_can_log_in_again():
    token, _ = _issue(ttl=timedelta(seconds=-120))

    with pytest.raises(SessionError) as error:
        verify_session_token(token, KEY)

    assert error.value.code == "session_expired"


def test_verify_rejects_a_token_signed_with_another_key():
    token, _ = _issue(signing_key="x" * 32)

    with pytest.raises(SessionError) as error:
        verify_session_token(token, KEY)

    assert error.value.code == "invalid_session"


def test_verify_rejects_alg_none():
    forged = jwt.encode(
        {
            "tid": str(uuid.uuid4()),
            "conv": str(uuid.uuid4()),
            "cid": str(uuid.uuid4()),
            "lvl": "store_login",
            "exp": 9**10,
        },
        None,
        algorithm="none",
    )

    with pytest.raises(SessionError):
        verify_session_token(forged, KEY)


def _ids(**changes):
    ids = {"tid": str(uuid.uuid4()), "conv": str(uuid.uuid4()), "cid": str(uuid.uuid4())}
    return {k: v for k, v in (ids | changes).items() if v is not None}


@pytest.mark.parametrize(
    "claims",
    [
        _ids(tid=None) | {"lvl": "store_login"},
        _ids(conv=None) | {"lvl": "store_login"},
        _ids(cid=None) | {"lvl": "store_login"},
        _ids() | {"lvl": "root"},
        _ids(tid="nope") | {"lvl": "store_login"},
        _ids(conv="nope") | {"lvl": "store_login"},
        _ids() | {"lvl": "anonymous"},
        _ids(),
    ],
    ids=[
        "no-tid",
        "no-conv",
        "identified-without-customer",
        "unknown-level",
        "tid-not-a-uuid",
        "conv-not-a-uuid",
        "anonymous-with-customer",
        "no-level",
    ],
)
def test_verify_rejects_a_signed_token_with_missing_or_inconsistent_claims(claims):
    with pytest.raises(SessionError) as error:
        verify_session_token(_forge(claims), KEY)

    assert error.value.code == "invalid_session"


def test_verify_rejects_garbage():
    with pytest.raises(SessionError):
        verify_session_token("not-a-jwt", KEY)
