"""The order id is typed like the identity inputs are: a shape check with no database behind
it, so a malformed id never reaches a query or a log line."""

import pytest
from pydantic import ValidationError

from app.schemas.orders import ORDER_ID_PATTERN, OrderDetails, OrderStatus, is_valid_order_id


@pytest.mark.parametrize("good", ["A1b2C3d4E5f6G7h8I9j0", "0" * 20, "a" * 20])
def test_accepts_exactly_twenty_alphanumeric_characters(good: str):
    assert is_valid_order_id(good)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "a" * 19,
        "a" * 21,
        "a" * 19 + "-",
        "a" * 19 + " ",
        "a" * 19 + "\n",  # `$` would let a trailing newline through
        "é" * 20,
        "٠" * 20,  # Arabic-Indic digits: `\\d` would accept them, `[0-9]` does not
        "a'; DROP TABLE orders;--",
    ],
)
def test_rejects_anything_else(bad: str):
    assert not is_valid_order_id(bad)


def test_the_model_validates_the_same_rule():
    fields = {
        "order_id": "a" * 20,
        "customer_email": "ava@example.com",
        "plan_slug": "starter",
        "amount_cents": 2900,
        "currency": "usd",
        "status": OrderStatus.PAID,
        "created_at": "2026-10-01T00:00:00Z",
    }
    assert OrderDetails(**fields).order_id == "a" * 20
    with pytest.raises(ValidationError):
        OrderDetails(**{**fields, "order_id": "short"})
    assert ORDER_ID_PATTERN.startswith("^")


def test_the_source_does_not_touch_the_database_for_a_malformed_id():
    import asyncio
    import uuid

    from app.orders.simulated import SimulatedOrderSource

    def no_database():
        raise AssertionError("a malformed id must not reach the database")

    source = SimulatedOrderSource(no_database)
    for bad in ("short", "a" * 19 + "\n", "x'; DROP TABLE orders;--"):
        assert asyncio.run(source.get_order(tenant_id=uuid.uuid4(), order_id=bad)) is None
