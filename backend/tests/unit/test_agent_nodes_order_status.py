"""The order_status step: it reads the order the session proved, through the shop's orders
interface, and nothing else. No LLM, no database."""

import uuid
from datetime import UTC, datetime

import pytest

from app.agent.nodes import order_status as order_status_module
from app.agent.nodes.order_status import get_customer_orders_node, get_order_status_node
from app.agent.nodes.response_writer import _build_context_blob
from app.schemas.orders import OrderDetails, OrderStatus

TENANT = str(uuid.uuid4())
ORDER_ID = "A1b2C3d4E5f6G7h8I9j0"


def _order(**changes) -> OrderDetails:
    fields = {
        "order_id": ORDER_ID,
        "customer_email": "ana@shop.test",
        "plan_slug": "pro",
        "amount_cents": 9900,
        "currency": "usd",
        "status": OrderStatus.PAID,
        "created_at": datetime(2026, 9, 17, tzinfo=UTC),
    }
    return OrderDetails(**(fields | changes))


class FakeOrders:
    def __init__(self, order: OrderDetails | None):
        self.order = order
        self.calls: list[dict] = []

    async def get_order(self, *, tenant_id, order_id):
        self.calls.append({"tenant_id": tenant_id, "order_id": order_id})
        return self.order

    async def list_orders(self, *, tenant_id, customer_id, limit=10):
        self.calls.append({"tenant_id": tenant_id, "customer_id": customer_id})
        return [self.order] if self.order else []


@pytest.fixture
def orders(monkeypatch):
    def install(order):
        fake = FakeOrders(order)
        monkeypatch.setattr(order_status_module, "get_order_source", lambda: fake)
        return fake

    return install


@pytest.mark.asyncio
async def test_it_reads_the_sessions_order_for_the_sessions_tenant(orders):
    fake = orders(_order())

    result = await get_order_status_node({"tenant_id": TENANT, "order_id": ORDER_ID})

    assert result["order_details"] == _order()
    assert fake.calls == [{"tenant_id": uuid.UUID(TENANT), "order_id": ORDER_ID}]


@pytest.mark.asyncio
async def test_an_order_that_is_no_longer_there_is_none_not_an_error(orders):
    orders(None)

    result = await get_order_status_node({"tenant_id": TENANT, "order_id": ORDER_ID})

    assert result == {"order_details": None}


@pytest.mark.asyncio
async def test_it_refuses_to_run_without_an_order_in_the_session(orders):
    fake = orders(_order())

    with pytest.raises(PermissionError):
        await get_order_status_node({"tenant_id": TENANT, "order_id": None})
    assert fake.calls == []


def test_the_writer_is_given_the_order_as_text_with_the_amount_already_in_dollars():
    blob = _build_context_blob({"order_details": _order()})

    assert "Order:" in blob and ORDER_ID in blob
    assert "$99.00" in blob and "paid" in blob and "pro" in blob and "2026-09-17" in blob
    assert "99.0" not in blob.replace("$99.00", "")  # no raw cents for the model to convert


def test_the_writer_is_told_when_the_order_could_not_be_found():
    blob = _build_context_blob({"order_details": None, "intent": "order_status"})

    assert "no order" in blob.lower()


def test_the_chat_hands_the_agent_the_tenant_and_the_order_of_the_session():
    from app.api.chat import _build_initial_state
    from app.auth.scopes import IdentityLevel
    from app.auth.session import SessionClaims

    session = SessionClaims(
        tenant_id=uuid.UUID(TENANT),
        conversation_id=uuid.uuid4(),
        customer_id=None,
        level=IdentityLevel.ORDER_LOOKUP,
        order_id=ORDER_ID,
    )
    turn = type("Turn", (), {"history": [], "user_text": "where is my order?", "pending_return": None})()

    state = _build_initial_state(turn, session)

    assert state["tenant_id"] == TENANT and state["order_id"] == ORDER_ID
    assert state["customer_id"] is None


CUSTOMER = str(uuid.uuid4())


@pytest.mark.asyncio
async def test_a_verified_customers_orders_are_read_for_the_session_customer(orders):
    fake = orders(_order(status=OrderStatus.OPEN))

    result = await get_customer_orders_node({"tenant_id": TENANT, "customer_id": CUSTOMER})

    assert [o.status for o in result["customer_orders"]] == [OrderStatus.OPEN]
    assert fake.calls == [{"tenant_id": uuid.UUID(TENANT), "customer_id": uuid.UUID(CUSTOMER)}]


@pytest.mark.asyncio
async def test_reading_a_customers_orders_needs_a_customer(orders):
    orders(None)

    with pytest.raises(ValueError, match="verified customer"):
        await get_customer_orders_node({"tenant_id": TENANT, "customer_id": None})


def test_the_writer_is_given_every_order_with_its_status_in_words():
    blob = _build_context_blob(
        {
            "intent": "order_status",
            "customer_orders": [
                _order(order_id="B" * 20, amount_cents=6999, status=OrderStatus.IN_DELIVERY),
                _order(amount_cents=2999, status=OrderStatus.OPEN),
            ],
        }
    )

    assert "$69.99" in blob and "in delivery (on its way)" in blob
    assert "$29.99" in blob and "open (not shipped yet)" in blob


def test_a_customer_without_orders_is_told_so_not_that_a_number_was_not_found():
    blob = _build_context_blob({"intent": "order_status", "customer_orders": []})

    assert "no orders" in blob and "no order with that number" not in blob
