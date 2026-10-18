"""What the audit record may hold about someone: enough for a person to recognise them and for
attempts by the same address to be grouped, without keeping the address, the order id or a code."""

import pytest

from app.auth.audit import hmac_value, mask_email

KEY = "k" * 32


@pytest.mark.parametrize(
    ("email", "masked"),
    [
        ("ana@shop.test", "a***@s***.test"),
        ("Ava.Chen@NorthlightStudio.com", "a***@n***.com"),
        ("x@y.io", "x***@y***.io"),
        ("first.last@mail.example.co.uk", "f***@m***.uk"),
    ],
)
def test_an_email_is_masked_to_its_first_letters(email, masked):
    assert mask_email(email) == masked


def test_a_masked_email_does_not_contain_the_address():
    email = "ava.chen@northlightstudio.com"
    masked = mask_email(email)

    assert email not in masked and "chen" not in masked and "northlight" not in masked


def test_the_hmac_groups_the_same_value_and_hides_it():
    first = hmac_value(KEY, "email", "ana@shop.test")

    assert first == hmac_value(KEY, "email", "ana@shop.test")
    assert first != hmac_value(KEY, "email", "bob@shop.test")
    assert "ana" not in first and len(first) == 64


def test_the_hmac_is_normalized_for_emails_and_separated_by_kind_and_key():
    assert hmac_value(KEY, "email", " ANA@Shop.Test ") == hmac_value(KEY, "email", "ana@shop.test")
    # An order id and an email never collide, and another key gives another value.
    assert hmac_value(KEY, "order", "ana@shop.test") != hmac_value(KEY, "email", "ana@shop.test")
    assert hmac_value("j" * 32, "email", "ana@shop.test") != hmac_value(KEY, "email", "ana@shop.test")
