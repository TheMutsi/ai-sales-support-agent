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


_CUSTOMER_BOUND = frozenset(
    {Scope.CUSTOMER_READ, Scope.TICKET_CREATE, Scope.SUBSCRIPTION_CHANGE, Scope.REFUND_REQUEST}
)
_LEVELS_WITHOUT_A_CUSTOMER = frozenset({IdentityLevel.ANONYMOUS, IdentityLevel.ORDER_LOOKUP})


def scopes_for(
    level: IdentityLevel, overrides: Mapping[str, Sequence[str]] | None = None
) -> frozenset[Scope]:
    if overrides and level.value in overrides:
        known = {s.value: s for s in Scope}
        granted = frozenset(known[name] for name in overrides[level.value] if name in known)
        if level in _LEVELS_WITHOUT_A_CUSTOMER:
            granted -= _CUSTOMER_BOUND
        return granted
    return DEFAULT_LEVEL_SCOPES[level]


def scope_override_problems(overrides: Mapping[str, Sequence[str]]) -> list[str]:
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
