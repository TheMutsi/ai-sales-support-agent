import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import jwt

logger = logging.getLogger(__name__)

MAX_TOKEN_LIFETIME_SECONDS = 3600
_CLOCK_SKEW_LEEWAY_SECONDS = 30


class StoreTokenError(Exception):
    def __init__(self, code: Literal["token_expired", "invalid_token"]):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StoreTokenClaims:
    customer_external_id: str
    exp: int


def verify_store_token(token: str, signing_keys: Mapping[str, str]) -> StoreTokenClaims:
    try:
        key = _select_key(token, signing_keys)
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
            leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError:
        raise StoreTokenError("token_expired") from None
    except (jwt.InvalidTokenError, _NoUsableKey) as exc:
        logger.warning("store token rejected: %s", exc)
        raise StoreTokenError("invalid_token") from None

    sub, exp = claims["sub"], claims["exp"]
    if not isinstance(sub, str) or not sub:
        raise StoreTokenError("invalid_token")
    if exp - time.time() > MAX_TOKEN_LIFETIME_SECONDS + _CLOCK_SKEW_LEEWAY_SECONDS:
        logger.warning("store token rejected: expires too far in the future")
        raise StoreTokenError("invalid_token")
    return StoreTokenClaims(customer_external_id=sub, exp=exp)


class _NoUsableKey(Exception):
    pass


def _select_key(token: str, signing_keys: Mapping[str, str]) -> str:
    kid = jwt.get_unverified_header(token).get("kid")
    if kid is not None:
        if not isinstance(kid, str) or kid not in signing_keys:
            raise _NoUsableKey(f"unknown kid {kid!r}")
        return signing_keys[kid]
    if len(signing_keys) == 1:
        return next(iter(signing_keys.values()))
    raise _NoUsableKey("no kid and not exactly one active secret")
