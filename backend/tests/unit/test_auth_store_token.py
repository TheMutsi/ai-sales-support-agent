import json
import time

import jwt
import pytest

from app.auth.store_token import StoreTokenError, verify_store_token

SECRET = "s" * 32


def _token(claims: dict | None = None, *, secret: str = SECRET, headers: dict | None = None) -> str:
    now = int(time.time())
    payload = {"sub": "cust-42", "iat": now, "exp": now + 300, **(claims or {})}
    return jwt.encode(payload, secret, algorithm="HS256", headers=headers)


def test_valid_token_returns_the_subject():
    claims = verify_store_token(_token(), {"k1": SECRET})

    assert claims.sub == "cust-42"


def test_wrong_secret_is_rejected_as_invalid():
    with pytest.raises(StoreTokenError) as error:
        verify_store_token(_token(secret="x" * 32), {"k1": SECRET})

    assert error.value.code == "invalid_token"


def test_expired_token_has_its_own_code_so_the_client_can_fetch_a_fresh_one():
    expired = _token({"exp": int(time.time()) - 120})

    with pytest.raises(StoreTokenError) as error:
        verify_store_token(expired, {"k1": SECRET})

    assert error.value.code == "token_expired"


@pytest.mark.parametrize("missing", ["sub", "exp"])
def test_required_claims_must_be_present(missing: str):
    now = int(time.time())
    payload = {"sub": "cust-42", "exp": now + 300}
    del payload[missing]
    token = jwt.encode(payload, SECRET, algorithm="HS256")

    with pytest.raises(StoreTokenError) as error:
        verify_store_token(token, {"k1": SECRET})

    assert error.value.code == "invalid_token"


def test_empty_subject_is_rejected():
    with pytest.raises(StoreTokenError):
        verify_store_token(_token({"sub": ""}), {"k1": SECRET})


def test_alg_none_is_rejected():
    forged = jwt.encode({"sub": "cust-42", "exp": int(time.time()) + 300}, None, algorithm="none")

    with pytest.raises(StoreTokenError) as error:
        verify_store_token(forged, {"k1": SECRET})

    assert error.value.code == "invalid_token"


def test_other_hmac_algorithms_are_rejected():
    token = jwt.encode(
        {"sub": "cust-42", "exp": int(time.time()) + 300}, SECRET * 2, algorithm="HS512"
    )

    with pytest.raises(StoreTokenError):
        verify_store_token(token, {"k1": SECRET * 2})


def test_kid_selects_the_matching_secret_during_a_rotation():
    old, new = "o" * 32, "n" * 32
    keys = {"old": old, "new": new}

    assert verify_store_token(_token(secret=new, headers={"kid": "new"}), keys).sub == "cust-42"
    assert verify_store_token(_token(secret=old, headers={"kid": "old"}), keys).sub == "cust-42"


def test_unknown_kid_is_rejected():
    with pytest.raises(StoreTokenError) as error:
        verify_store_token(_token(headers={"kid": "ghost"}), {"k1": SECRET})

    assert error.value.code == "invalid_token"


@pytest.mark.parametrize("kid", [["k1"], {}, 7])
def test_non_string_kid_is_rejected_not_a_server_error(kid):
    # PyJWT refuses to *encode* such a header, so build the hostile token by hand.
    # The signature is junk; the kid check must reject it before getting that far.
    def segment(data: dict) -> str:
        return jwt.utils.base64url_encode(json.dumps(data).encode()).decode()

    header = segment({"alg": "HS256", "typ": "JWT", "kid": kid})
    payload = segment({"sub": "cust-42", "exp": int(time.time()) + 300})
    forged = f"{header}.{payload}.c2ln"

    with pytest.raises(StoreTokenError) as error:
        verify_store_token(forged, {"k1": SECRET})

    assert error.value.code == "invalid_token"


def test_missing_kid_uses_the_only_active_secret():
    assert verify_store_token(_token(), {"k1": SECRET}).sub == "cust-42"


def test_missing_kid_is_ambiguous_with_several_active_secrets():
    with pytest.raises(StoreTokenError):
        verify_store_token(_token(), {"k1": SECRET, "k2": "z" * 32})


def test_no_active_secrets_rejects_everything():
    with pytest.raises(StoreTokenError):
        verify_store_token(_token(), {})


def test_token_that_outlives_the_maximum_lifetime_is_rejected():
    """A shop minting day-long tokens would defeat the point of short-lived ones."""
    far_future = _token({"exp": int(time.time()) + 24 * 3600})

    with pytest.raises(StoreTokenError) as error:
        verify_store_token(far_future, {"k1": SECRET})

    assert error.value.code == "invalid_token"


def test_garbage_is_rejected_without_leaking_detail():
    with pytest.raises(StoreTokenError) as error:
        verify_store_token("not-a-jwt", {"k1": SECRET})

    assert error.value.code == "invalid_token"
