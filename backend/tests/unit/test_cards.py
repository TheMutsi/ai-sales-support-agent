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

    assert [c.type for c in cards] == ["product", "action", "action", "action", "action"]
    product, refund, points, free, reject = cards
    assert (product.name, product.price, product.badge) == ("Pro plan", "$69.99", "Open")
    assert (refund.title, refund.badge) == ("$14.00 back to your card", "20% back")
    assert refund.message == "I'll take the $14.00 refund to my card"
    assert (points.title, points.message) == ("2,100 points", "I'll take the 2,100 points")
    assert (free.title, free.badge, free.message) == ("Your next order, free", "Free", "I'll take the next order free")
    assert reject.id == "offer-reject"


def test_a_cancellation_to_confirm_offers_yes_and_no():
    cards = cards_for(_result(ReturnOutcome.CONFIRM_CANCEL, order=_order(cents=2999)))

    assert [c.id for c in cards[1:]] == ["confirm-yes", "confirm-no"]
    assert cards[1].message == "Yes, cancel it"


def test_several_orders_to_choose_from_become_cards_that_name_the_order():
    first, second = _order(order_id="A" * 20), _order(cents=2999, slug="starter", order_id="B" * 20)

    cards = cards_for(_result(ReturnOutcome.CHOOSE_ORDER, candidates=[first, second]))

    assert [c.message for c in cards] == [
        "I mean the Pro plan order of $69.99 placed Oct 01",
        "I mean the Starter plan order of $29.99 placed Oct 01",
    ]
    assert all("A" * 20 not in (c.title + c.message) for c in cards)  # the visitor never sees an id
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


def test_a_card_type_that_no_longer_exists_does_not_break_reading_old_messages():
    from app.schemas.chat import StoredMessage

    message = StoredMessage.model_validate(
        {
            "seq": 1, "role": "assistant", "kind": "text", "content": "x", "created_at": "2026-10-19T00:00:00Z",
            "cards": [{"type": "carousel", "id": "old"}, {"type": "action", "id": "a", "title": "t", "message": "m"}],
        }
    )

    assert [c.id for c in message.cards] == ["a"]


def test_an_offer_without_its_order_shows_nothing():
    assert cards_for(_result(ReturnOutcome.OFFER, offer=RetentionOffer(refund_cents=1, credit_points=1))) == []


def test_taking_the_free_next_order_shows_the_coupon_that_was_recorded():
    from app.schemas.orders import RetentionChoice, RetentionReceipt

    receipt = RetentionReceipt(order_id="A" * 20, choice=RetentionChoice.NEXT_ORDER_FREE, coupon_code="FREE-AAAAAA")

    cards = cards_for(_result(ReturnOutcome.KEPT_WITH_FREE_ORDER, order=_order(), receipt=receipt))

    assert [(c.type, c.code) for c in cards] == [("coupon", "FREE-AAAAAA")]
    assert cards_for(_result(ReturnOutcome.KEPT_WITH_FREE_ORDER, order=_order())) == []  # no code, no coupon


def test_the_last_offer_shows_the_free_gift_then_a_plus_then_the_same_choices():
    cards = cards_for(
        _result(ReturnOutcome.FINAL_OFFER, order=_order(), offer=RetentionOffer(refund_cents=1400, credit_points=2100))
    )

    assert [c.type for c in cards] == ["product", "divider", "action", "action", "action", "action"]
    gift, plus, refund, points, free, cancel = cards
    assert (gift.name, gift.price, gift.badge) == ("Mew hoodie", "FREE", "Free gift")
    assert gift.image.url == "/api/assets/products/gift.svg" and plus.label == "+"
    assert [refund.id, points.id, free.id] == ["offer-refund", "offer-points", "offer-free"]
    assert cancel.message == "No, cancel my order"


def test_taking_an_offer_at_the_last_chance_shows_the_gift_that_comes_with_it():
    from app.schemas.orders import RetentionChoice, RetentionReceipt

    receipt = RetentionReceipt(order_id="A" * 20, choice=RetentionChoice.CREDITS, credit_points=2100, gift="Mew hoodie")
    plain = RetentionReceipt(order_id="A" * 20, choice=RetentionChoice.CREDITS, credit_points=2100)

    with_gift = cards_for(_result(ReturnOutcome.KEPT_WITH_CREDITS, order=_order(), receipt=receipt))
    without = cards_for(_result(ReturnOutcome.KEPT_WITH_CREDITS, order=_order(), receipt=plain))

    assert [(c.type, c.badge) for c in with_gift] == [("product", "Your gift")]
    assert without == []
