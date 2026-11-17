from datetime import UTC, datetime, time

import pytest

from app.business.escalation import (
    EscalationRoute,
    RouteReason,
    RoutingFacts,
    SupportHours,
    decide_route,
)
from app.schemas.orders import OrderStatus

WEEKDAYS = frozenset(range(5))
HOURS = SupportHours("UTC", time(9), time(18), WEEKDAYS)
TUESDAY_NOON = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
TUESDAY_NIGHT = datetime(2026, 11, 3, 22, 0, tzinfo=UTC)
SATURDAY_NOON = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _facts(**overrides) -> RoutingFacts:
    base = {"now": TUESDAY_NOON, "support_hours": HOURS, "agents_available": 1}
    return RoutingFacts(**{**base, **overrides})


def test_goes_live_when_the_team_is_open_and_someone_is_there():
    decision = decide_route(_facts())
    assert (decision.route, decision.reason) == (EscalationRoute.LIVE, RouteReason.AGENT_AVAILABLE)


def test_goes_offline_outside_the_hours_even_with_an_agent_around():
    for moment in (TUESDAY_NIGHT, SATURDAY_NOON):
        decision = decide_route(_facts(now=moment))
        assert (decision.route, decision.reason) == (
            EscalationRoute.OFFLINE,
            RouteReason.OUTSIDE_SUPPORT_HOURS,
        )


def test_goes_offline_when_no_agent_is_available():
    decision = decide_route(_facts(agents_available=0))
    assert (decision.route, decision.reason) == (
        EscalationRoute.OFFLINE,
        RouteReason.NO_AGENT_AVAILABLE,
    )


def test_an_order_on_its_way_is_not_urgent_even_with_everyone_there():
    decision = decide_route(_facts(order_status=OrderStatus.IN_DELIVERY))
    assert (decision.route, decision.reason) == (EscalationRoute.OFFLINE, RouteReason.NOT_URGENT)


def test_an_order_not_shipped_yet_still_gets_a_person():
    assert decide_route(_facts(order_status=OrderStatus.OPEN)).route is EscalationRoute.LIVE


def test_no_schedule_means_always_open():
    assert decide_route(_facts(support_hours=None, now=SATURDAY_NOON)).route is EscalationRoute.LIVE


def test_hours_are_read_in_the_shops_time_zone():
    buenos_aires = SupportHours("America/Argentina/Buenos_Aires", time(9), time(18), WEEKDAYS)
    assert not buenos_aires.is_open(TUESDAY_NIGHT)
    assert buenos_aires.is_open(datetime(2026, 11, 3, 15, 0, tzinfo=UTC))


def test_a_night_shift_runs_past_midnight_from_the_day_it_started():
    night = SupportHours("UTC", time(22), time(6), frozenset({0}))
    monday_late = datetime(2026, 11, 2, 23, 0, tzinfo=UTC)
    tuesday_early = datetime(2026, 11, 3, 5, 0, tzinfo=UTC)
    tuesday_late = datetime(2026, 11, 3, 23, 0, tzinfo=UTC)
    sunday_early = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
    assert night.is_open(monday_late) and night.is_open(tuesday_early)
    assert not night.is_open(tuesday_late) and not night.is_open(sunday_early)
    assert not night.is_open(datetime(2026, 11, 3, 12, 0, tzinfo=UTC))


def test_a_schedule_that_opens_and_closes_at_once_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        SupportHours.from_config({"timezone": "UTC", "opens": "09:00", "closes": "09:00", "weekdays": [0]})


def test_routing_facts_refuse_a_naive_time():
    with pytest.raises(ValueError):
        _facts(now=TUESDAY_NOON.replace(tzinfo=None))
