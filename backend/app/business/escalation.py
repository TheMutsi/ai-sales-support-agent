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
    NOT_URGENT = "not_urgent"
    OUTSIDE_SUPPORT_HOURS = "outside_support_hours"
    NO_AGENT_AVAILABLE = "no_agent_available"


def _reject_unknown_timezone(name: str) -> None:
    ZoneInfo(name)


@dataclass(frozen=True)
class SupportHours:
    timezone: str
    opens: time
    closes: time
    weekdays: frozenset[int]

    @classmethod
    def from_config(cls, raw: dict | None) -> "SupportHours | None":
        if not raw:
            return None
        hours = cls(
            timezone=raw["timezone"],
            opens=time.fromisoformat(raw["opens"]),
            closes=time.fromisoformat(raw["closes"]),
            weekdays=frozenset(int(day) for day in raw["weekdays"]),
        )
        _reject_unknown_timezone(hours.timezone)
        if hours.opens == hours.closes:
            raise ValueError("support hours open and close at the same time")
        return hours

    def is_open(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(self.timezone))
        day, moment = local.weekday(), local.time()
        if self.opens < self.closes:
            return day in self.weekdays and self.opens <= moment < self.closes
        if moment >= self.opens:
            return day in self.weekdays
        return moment < self.closes and (day - 1) % 7 in self.weekdays


@dataclass(frozen=True)
class RoutingFacts:
    now: datetime
    support_hours: SupportHours | None
    agents_available: int
    order_status: OrderStatus | None = None

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("RoutingFacts.now must be timezone-aware")


@dataclass(frozen=True)
class RouteDecision:
    route: EscalationRoute
    reason: RouteReason


_NOT_URGENT_ORDER_STATUSES = frozenset({OrderStatus.IN_DELIVERY})


def decide_route(facts: RoutingFacts) -> RouteDecision:
    if facts.order_status in _NOT_URGENT_ORDER_STATUSES:
        return RouteDecision(EscalationRoute.OFFLINE, RouteReason.NOT_URGENT)
    if facts.support_hours is not None and not facts.support_hours.is_open(facts.now):
        return RouteDecision(EscalationRoute.OFFLINE, RouteReason.OUTSIDE_SUPPORT_HOURS)
    if facts.agents_available < 1:
        return RouteDecision(EscalationRoute.OFFLINE, RouteReason.NO_AGENT_AVAILABLE)
    return RouteDecision(EscalationRoute.LIVE, RouteReason.AGENT_AVAILABLE)
