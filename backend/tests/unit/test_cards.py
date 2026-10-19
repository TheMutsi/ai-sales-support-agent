"""Which cards a turn shows. They come from what the steps really produced, never from the reply."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.cards import cards_for
from app.main import app
from app.schemas.orders import (
    OrderDetails,
    OrderStatus,
    RetentionOffer,
    ReturnOutcome,
    ReturnResult,
)


def _order(status=OrderStatus.OPEN, cents=6999, slug="pro", order_id="A" * 20) -> OrderDetails:
    return OrderDetails(
        order_id=order_id, customer_email="mail2@gmail.com", plan_slug=slug, amount_cents=cents,
        currency="usd", status=status, created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def _result(outcome, **kw) -> dict:
    return {"return_result": ReturnResult(outcome=outcome, **kw)}


def test_an_offer_shows_the_order_and_one_card_per_choice_with_the_numbers_from_the_rules():
    cards = cards_for(
        _result(ReturnOutcome.OFFER, order=_order(), offer=RetentionOffer(refund_cents=1400, credit_points=2100))
    )

    assert [c.type for c in cards] == ["product", "action", "action", "action"]
    product, refund, points, reject = cards
    assert (product.name, product.price, product.badge) == ("Pro plan", "$69.99", "Open")
    assert (refund.title, refund.badge) == ("$14.00 back to your card", "20% back")
    assert refund.message == "I'll take the $14.00 refund to my card"
    assert (points.title, points.message) == ("2,100 points", "I'll take the 2,100 points")
    assert reject.id == "offer-reject"


def test_a_cancellation_to_confirm_offers_yes_and_no():
    cards = cards_for(_result(ReturnOutcome.CONFIRM_CANCEL, order=_order(cents=2999)))

    assert [c.id for c in cards[1:]] == ["confirm-yes", "confirm-no"]
    assert cards[1].message == "Yes, cancel it"


def test_several_orders_to_choose_from_become_cards_that_name_the_order():
    first, second = _order(order_id="A" * 20), _order(cents=2999, slug="starter", order_id="B" * 20)

    cards = cards_for(_result(ReturnOutcome.CHOOSE_ORDER, candidates=[first, second]))

    assert [c.message for c in cards] == [f"I mean order {'A' * 20}", f"I mean order {'B' * 20}"]
    assert cards[1].title == "Starter plan, $29.99"


def test_a_customers_orders_are_shown_as_product_cards():
    cards = cards_for({"customer_orders": [_order(OrderStatus.IN_DELIVERY)]})

    assert [(c.type, c.badge) for c in cards] == [("product", "In delivery")]
    assert cards[0].image.url == "/api/assets/products/pro.svg"


def test_outcomes_that_ask_nothing_and_ordinary_turns_show_no_cards():
    assert cards_for({}) == []
    assert cards_for(_result(ReturnOutcome.CANCELLED, order=_order())) == []
    assert cards_for(_result(ReturnOutcome.RETURN_LATER, order=_order())) == []


def test_a_plan_picture_is_drawn_for_known_plans_only():
    client = TestClient(app)

    known = client.get("/api/assets/products/pro.svg")
    unknown = client.get("/api/assets/products/<script>.svg")

    assert known.status_code == 200 and known.headers["content-type"] == "image/svg+xml"
    assert "Pro" in known.text and "<script" not in known.text
    assert unknown.status_code == 404
