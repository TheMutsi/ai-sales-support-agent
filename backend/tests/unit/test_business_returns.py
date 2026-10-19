"""What may be done with an order a customer does not want, and what is offered to keep it.
Pure rules: no database, no model."""

from datetime import UTC, datetime

import pytest

from app.business.returns import retention_offer, return_options
from app.schemas.orders import OrderDetails, OrderStatus


def _order(status: OrderStatus, amount_cents: int) -> OrderDetails:
    return OrderDetails(
        order_id="A1b2C3d4E5f6G7h8I9j0",
        customer_email="mail1@gmail.com",
        plan_slug="starter",
        amount_cents=amount_cents,
        currency="usd",
        status=status,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def test_the_offer_for_69_99_is_14_dollars_back_or_2100_points():
    offer = retention_offer(6999)

    assert offer is not None
    assert offer.refund_cents == 1400  # 20% of 69.99 = 13.998, rounded to the cent
    assert offer.credit_points == 2100  # 30% = 20.997 dollars, one point per cent


@pytest.mark.parametrize("amount", [2999, 4999, 0])
def test_cheaper_orders_are_not_offered_anything(amount):
    assert retention_offer(amount) is None


def test_the_threshold_itself_is_offered():
    offer = retention_offer(5000)

    assert offer is not None and (offer.refund_cents, offer.credit_points) == (1000, 1500)


def test_an_open_order_can_be_cancelled_and_the_expensive_one_gets_the_offer_first():
    cheap, expensive = return_options(_order(OrderStatus.OPEN, 2999)), return_options(
        _order(OrderStatus.OPEN, 6999)
    )

    assert (cheap.can_cancel, cheap.return_after_delivery, cheap.retention) == (True, False, None)
    assert expensive.can_cancel and expensive.retention is not None


def test_an_order_on_its_way_cannot_be_rejected_only_returned_later():
    cheap, expensive = return_options(_order(OrderStatus.IN_DELIVERY, 2999)), return_options(
        _order(OrderStatus.IN_DELIVERY, 6999)
    )

    assert (cheap.can_cancel, cheap.return_after_delivery, cheap.retention) == (False, True, None)
    assert not expensive.can_cancel and expensive.return_after_delivery
    assert expensive.retention is not None  # the same offer to keep it


@pytest.mark.parametrize("status", [OrderStatus.CANCELLED, OrderStatus.PAID, OrderStatus.REFUNDED])
def test_other_statuses_allow_and_offer_nothing(status):
    options = return_options(_order(status, 6999))

    assert (options.can_cancel, options.return_after_delivery, options.retention) == (False, False, None)


def test_rounding_is_half_up_in_integer_cents():
    offer = retention_offer(5005)  # 30% = 1501.5 cents

    assert offer is not None and offer.credit_points == 1502
