"""Where an escalation goes: to a person in the chat now, or to a person who follows up later.

A live agent (the conversation waits for someone to join, see `app.chat.handoff`) costs somebody's
attention right now, so it is kept for what needs it and when someone can answer. Everything else
gets an offline escalation: the customer is given a follow-up number, kept on the conversation, and a
person writes back later. The rules are ordered and decided here, from facts the caller collected,
never by the model.
"""

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.schemas.orders import OrderStatus


class EscalationRoute(StrEnum):
    LIVE = "live"
    OFFLINE = "offline"


class RouteReason(StrEnum):
    AGENT_AVAILABLE = "agent_available"
    NOT_URGENT = "not_urgent"  # nothing a person could do right now (the order is on its way)
    OUTSIDE_SUPPORT_HOURS = "outside_support_hours"
    NO_AGENT_AVAILABLE = "no_agent_available"


@dataclass(frozen=True)
class SupportHours:
    """When the shop's team answers: the weekdays (Monday is 0) between `opens` and `closes`, in
    the shop's own time zone."""

    timezone: str
    opens: time
    closes: time
    weekdays: frozenset[int]

    @classmethod
    def from_config(cls, raw: dict | None) -> "SupportHours | None":
        """Reads a tenant's stored schedule (see `Tenant.support_hours`); empty means always."""
        if not raw:
            return None
        hours = cls(
            timezone=raw["timezone"],
            opens=time.fromisoformat(raw["opens"]),
            closes=time.fromisoformat(raw["closes"]),
            weekdays=frozenset(int(day) for day in raw["weekdays"]),
        )
        ZoneInfo(hours.timezone)  # an unknown zone fails here, not on a customer's turn
        return hours

    def is_open(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(self.timezone))
        return local.weekday() in self.weekdays and self.opens <= local.time() < self.closes


@dataclass(frozen=True)
class RoutingFacts:
    now: datetime  # timezone-aware
    # None means no schedule was set: the team is taken as always there.
    support_hours: SupportHours | None
    # Back-office agents who have been seen recently (see `app.chat.presence`).
    agents_available: int
    # The order the escalation is about, when there is one.
    order_status: OrderStatus | None = None


@dataclass(frozen=True)
class RouteDecision:
    route: EscalationRoute
    reason: RouteReason


# An order already on its way cannot be changed by anyone: the customer will return it once it
# arrives, so insisting does not need a person this minute.
_NOT_URGENT_ORDER_STATUSES = frozenset({OrderStatus.IN_DELIVERY})


def decide_route(facts: RoutingFacts) -> RouteDecision:
    if facts.order_status in _NOT_URGENT_ORDER_STATUSES:
        return RouteDecision(EscalationRoute.OFFLINE, RouteReason.NOT_URGENT)
    if facts.support_hours is not None and not facts.support_hours.is_open(facts.now):
        return RouteDecision(EscalationRoute.OFFLINE, RouteReason.OUTSIDE_SUPPORT_HOURS)
    if facts.agents_available < 1:
        return RouteDecision(EscalationRoute.OFFLINE, RouteReason.NO_AGENT_AVAILABLE)
    return RouteDecision(EscalationRoute.LIVE, RouteReason.AGENT_AVAILABLE)
