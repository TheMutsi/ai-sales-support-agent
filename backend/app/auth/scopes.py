"""What each way of identifying a visitor entitles them to do.

A visitor reaches the chat at one of four identity levels, and each level maps
to a set of scopes. Tools declare the scope they need; a deterministic check
compares it with the visitor's scopes — the LLM never decides whether someone
is allowed to do something (CLAUDE.md, principle 1).

`STORE_LOGIN` and `OTP_LOGIN` carry the same scopes on purpose: they prove the
same fact (who the customer is) by different routes — the shop vouching for
them with a signed token, or the customer confirming their email with a
one-time code (passwordless login). `ORDER_LOOKUP` is the weak one: a
reference number leaks easily, so it only ever allows read-only status checks.

The defaults live here; a tenant can override a level's scopes (stored as JSON
on the tenant, editable from a future backoffice).
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum


class Scope(StrEnum):
    KB_READ = "kb:read"
    CUSTOMER_READ = "customer:read"
    ORDER_READ = "order:read"
    TICKET_CREATE = "ticket:create"
    SUBSCRIPTION_CHANGE = "subscription:change"
    REFUND_REQUEST = "refund:request"


class IdentityLevel(StrEnum):
    ANONYMOUS = "anonymous"
    STORE_LOGIN = "store_login"
    OTP_LOGIN = "otp_login"
    ORDER_LOOKUP = "order_lookup"


_VERIFIED_CUSTOMER = frozenset(
    {
        Scope.KB_READ,
        Scope.CUSTOMER_READ,
        Scope.TICKET_CREATE,
        Scope.SUBSCRIPTION_CHANGE,
        Scope.REFUND_REQUEST,
    }
)

DEFAULT_LEVEL_SCOPES: Mapping[IdentityLevel, frozenset[Scope]] = {
    IdentityLevel.ANONYMOUS: frozenset({Scope.KB_READ}),
    IdentityLevel.STORE_LOGIN: _VERIFIED_CUSTOMER,
    IdentityLevel.OTP_LOGIN: _VERIFIED_CUSTOMER,
    IdentityLevel.ORDER_LOOKUP: frozenset({Scope.KB_READ, Scope.ORDER_READ}),
}


def scopes_for(
    level: IdentityLevel, overrides: Mapping[str, Sequence[str]] | None = None
) -> frozenset[Scope]:
    """Scopes granted at `level`, honoring a tenant's per-level overrides.

    Unknown scope names in an override are dropped rather than granted or
    raised on: a typo in configuration must never widen access, and one bad
    entry shouldn't lock a tenant out entirely."""
    if overrides and level.value in overrides:
        known = {s.value: s for s in Scope}
        return frozenset(known[name] for name in overrides[level.value] if name in known)
    return DEFAULT_LEVEL_SCOPES[level]
