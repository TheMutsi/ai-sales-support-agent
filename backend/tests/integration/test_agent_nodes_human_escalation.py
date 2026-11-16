"""The human_escalation node decides where an escalation goes and gives it a follow-up number. It
needs a real DB because it asks which agents are around, and the tenant's schedule."""

from datetime import UTC, datetime, time, timedelta

import pytest

from app.agent.nodes import human_escalation as human_escalation_module
from app.auth.credentials import generate_api_key
from app.business.escalation import EscalationRoute, RouteReason, SupportHours
from app.chat import presence
from app.core.tenant_config import tenant_configs
from app.db.models import Customer, Tenant
from app.db.session import SessionLocal
from app.schemas.agent import Intent
from app.schemas.orders import OrderDetails, OrderStatus, ReturnOutcome, ReturnResult
from app.schemas.tools import EscalationCategory, EscalationReceipt


@pytest.fixture
def shop(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.flush()
        customer = Customer(name="Ana", email="ana@shop.test", tenant_id=tenant.id)
        db.add(customer)
        db.commit()
        yield {"tenant": tenant, "customer": customer}


def _state(shop, **overrides) -> dict:
    return {
        "customer_id": str(shop["customer"].id), "tenant_id": str(shop["tenant"].id),
        "intent": Intent.REFUND_REQUEST, "messages": [], **overrides,
    }


def _an_agent_is_there(shop) -> None:
    with SessionLocal() as db:
        presence.touch(db, tenant_id=shop["tenant"].id, agent_name="Mónica", now=datetime.now(UTC))


def _order(status: OrderStatus) -> OrderDetails:
    return OrderDetails(
        order_id="a" * 20, customer_email="ana@shop.test", plan_slug="pro", amount_cents=2999,
        currency="usd", status=status, created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def test_goes_live_with_the_category_of_the_intent_when_an_agent_is_there(shop):
    _an_agent_is_there(shop)

    result = human_escalation_module.human_escalation_node(_state(shop))

    receipt = result["escalation_receipt"]
    assert result["escalated"] is True
    assert (receipt.route, receipt.reason) == (EscalationRoute.LIVE, RouteReason.AGENT_AVAILABLE)
    assert receipt.category is EscalationCategory.REFUND
    assert receipt.reference.startswith("MF-") and len(receipt.reference) == 11


def test_goes_offline_when_nobody_is_there(shop):
    receipt = human_escalation_module.human_escalation_node(_state(shop))["escalation_receipt"]
    assert (receipt.route, receipt.reason) == (EscalationRoute.OFFLINE, RouteReason.NO_AGENT_AVAILABLE)


def test_an_agent_not_seen_for_a_while_does_not_count(shop):
    with SessionLocal() as db:
        long_ago = datetime.now(UTC) - presence.AVAILABLE_FOR - timedelta(seconds=5)
        presence.touch(db, tenant_id=shop["tenant"].id, agent_name="Mónica", now=long_ago)
    receipt = human_escalation_module.human_escalation_node(_state(shop))["escalation_receipt"]
    assert receipt.route is EscalationRoute.OFFLINE


def test_goes_offline_outside_the_tenants_support_hours_even_with_an_agent(shop):
    _an_agent_is_there(shop)
    now = datetime.now(UTC)
    closed_now = SupportHours("UTC", time(0), time(0, 1), frozenset({(now.weekday() + 1) % 7}))
    tenant_configs.get(shop["tenant"].id)  # load the snapshot
    with SessionLocal() as db:
        tenant = db.get(Tenant, shop["tenant"].id)
        tenant.support_hours = {
            "timezone": closed_now.timezone, "opens": "00:00", "closes": "00:01",
            "weekdays": sorted(closed_now.weekdays),
        }
        db.commit()
    tenant_configs.invalidate()

    receipt = human_escalation_module.human_escalation_node(_state(shop))["escalation_receipt"]

    assert (receipt.route, receipt.reason) == (EscalationRoute.OFFLINE, RouteReason.OUTSIDE_SUPPORT_HOURS)


def test_a_customer_insisting_on_an_order_on_its_way_gets_a_number_not_a_person(shop):
    _an_agent_is_there(shop)
    result = ReturnResult(outcome=ReturnOutcome.ESCALATED, order=_order(OrderStatus.IN_DELIVERY))

    receipt = human_escalation_module.human_escalation_node(_state(shop, return_result=result))["escalation_receipt"]

    assert (receipt.route, receipt.reason) == (EscalationRoute.OFFLINE, RouteReason.NOT_URGENT)


def test_an_order_not_shipped_yet_still_goes_to_a_person_who_is_there(shop):
    _an_agent_is_there(shop)
    result = ReturnResult(outcome=ReturnOutcome.ESCALATED, order=_order(OrderStatus.OPEN))
    receipt = human_escalation_module.human_escalation_node(_state(shop, return_result=result))["escalation_receipt"]
    assert receipt.route is EscalationRoute.LIVE


def test_an_unmapped_intent_is_filed_as_other(shop):
    receipt = human_escalation_module.human_escalation_node(_state(shop, intent=Intent.UNSUPPORTED))
    assert receipt["escalation_receipt"].category is EscalationCategory.OTHER


def test_an_escalation_already_open_is_reused_with_its_number(shop):
    existing = EscalationReceipt(
        reference="MF-KEEPTHIS", route="offline", reason="no_agent_available", category="refund"
    )
    result = human_escalation_module.human_escalation_node(_state(shop, open_escalation=existing))
    assert result["escalation_receipt"] is existing


def test_without_a_customer_there_is_nothing_to_follow_up(shop):
    with pytest.raises(PermissionError):
        human_escalation_module.human_escalation_node(_state(shop, customer_id=None))


def test_the_references_are_distinct_and_use_no_look_alike_characters():
    from app.tools.escalation import new_reference

    references = {new_reference() for _ in range(200)}
    assert len(references) == 200
    assert not any(set("01OIL") & set(ref[3:]) for ref in references)
