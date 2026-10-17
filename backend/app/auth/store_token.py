"""Verifies the short-lived JWT a shop's server mints to vouch for a logged-in
customer (the `store_login` identity level).

The shop signs the token with a secret *we* issued it when it signed up (same
model as Zendesk's shared secret or Intercom's messenger secret), so verifying
is a local HMAC check against that tenant's stored secret — no external call.
The tenant is resolved from the public API key *before* this runs, so a token
can only ever be checked against its own tenant's keys.

Hardening that's easy to get wrong, and why it's here:
- `algorithms=["HS256"]` is fixed by us, never read from the token's header, or
  an attacker could pick `alg: none` and skip the signature entirely.
- `exp` and `sub` are required, and `exp` may not be further than
  `MAX_TOKEN_LIFETIME` away, so a shop can't mint effectively non-expiring
  tokens. These are single-use login tokens; the longer-lived credential is the
  session we issue in exchange.
- `kid` picks the secret during a rotation (two active at once). Without one we
  fall back to the only active secret; with several that's ambiguous, so reject.
- Callers get a stable code (`token_expired` is renewable by asking the shop for
  a fresh token; `invalid_token` is an integration error), never the library's
  message, which would tell a prober which check failed.
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import jwt

logger = logging.getLogger(__name__)

MAX_TOKEN_LIFETIME_SECONDS = 3600
_LEEWAY_SECONDS = 30  # tolerated clock skew between the shop's server and ours


class StoreTokenError(Exception):
    def __init__(self, code: Literal["token_expired", "invalid_token"]):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StoreTokenClaims:
    sub: str  # the shop's own identifier for the customer (maps to Customer.external_id)
    exp: int


def verify_store_token(token: str, signing_keys: Mapping[str, str]) -> StoreTokenClaims:
    """`signing_keys` maps `kid` -> secret for the tenant's currently active secrets."""
    try:
        key = _select_key(token, signing_keys)
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
            leeway=_LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError:
        raise StoreTokenError("token_expired") from None
    except (jwt.InvalidTokenError, _NoUsableKey) as exc:
        logger.warning("store token rejected: %s", exc)
        raise StoreTokenError("invalid_token") from None

    sub, exp = claims["sub"], claims["exp"]
    if not isinstance(sub, str) or not sub:
        raise StoreTokenError("invalid_token")
    if exp - time.time() > MAX_TOKEN_LIFETIME_SECONDS + _LEEWAY_SECONDS:
        logger.warning("store token rejected: expires too far in the future")
        raise StoreTokenError("invalid_token")
    return StoreTokenClaims(sub=sub, exp=exp)


class _NoUsableKey(Exception):
    pass


def _select_key(token: str, signing_keys: Mapping[str, str]) -> str:
    kid = jwt.get_unverified_header(token).get("kid")
    if kid is not None:
        # The header is attacker-controlled: an unhashable `kid` would raise
        # TypeError on the lookup below. Recent PyJWT rejects it earlier, but the
        # pinned floor (>=2.8) may not, so don't rely on the library for this.
        if not isinstance(kid, str) or kid not in signing_keys:
            raise _NoUsableKey(f"unknown kid {kid!r}")
        return signing_keys[kid]
    if len(signing_keys) == 1:
        return next(iter(signing_keys.values()))
    raise _NoUsableKey("no kid and not exactly one active secret")
