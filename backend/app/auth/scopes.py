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
        Scope.ORDER_READ,
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


# Scopes that act on a customer. A level that proves no customer (anonymous, or an order id)
# can never hold one: the nodes behind them need a customer and fail without it, so granting
# one would turn "please identify" into a server error.
_CUSTOMER_BOUND = frozenset(
    {Scope.CUSTOMER_READ, Scope.TICKET_CREATE, Scope.SUBSCRIPTION_CHANGE, Scope.REFUND_REQUEST}
)
_LEVELS_WITHOUT_A_CUSTOMER = frozenset({IdentityLevel.ANONYMOUS, IdentityLevel.ORDER_LOOKUP})


def scopes_for(
    level: IdentityLevel, overrides: Mapping[str, Sequence[str]] | None = None
) -> frozenset[Scope]:
    """Scopes granted at `level`, honoring a tenant's per-level overrides.

    Unknown scope names in an override are dropped rather than granted or
    raised on: a typo in configuration must never widen access, and one bad
    entry shouldn't lock a tenant out entirely."""
    if overrides and level.value in overrides:
        known = {s.value: s for s in Scope}
        granted = frozenset(known[name] for name in overrides[level.value] if name in known)
        if level in _LEVELS_WITHOUT_A_CUSTOMER:
            granted -= _CUSTOMER_BOUND
        return granted
    return DEFAULT_LEVEL_SCOPES[level]


def scope_override_problems(overrides: Mapping[str, Sequence[str]]) -> list[str]:
    """What is wrong with a tenant's overrides, for the back office to refuse them up front.
    `scopes_for` drops these silently at request time (a typo must never widen access); an
    administrator saving them should be told instead of believing they took effect."""
    known_scopes = {s.value for s in Scope}
    levels = {level.value: level for level in IdentityLevel}
    problems = []
    for level_name, scope_names in overrides.items():
        if level_name not in levels:
            problems.append(f"unknown identity level {level_name!r}")
            continue
        for name in scope_names:
            if name not in known_scopes:
                problems.append(f"unknown scope {name!r} for {level_name}")
            elif (
                levels[level_name] in _LEVELS_WITHOUT_A_CUSTOMER
                and Scope(name) in _CUSTOMER_BOUND
            ):
                problems.append(f"{name} cannot be granted at {level_name}: it proves no customer")
    return problems
