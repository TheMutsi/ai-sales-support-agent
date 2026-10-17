import pytest

from app.core.origins import normalize_origin


@pytest.mark.parametrize(
    "given, expected",
    [
        ("https://shop.example", "https://shop.example"),
        ("HTTPS://Shop.Example", "https://shop.example"),
        ("https://shop.example:443", "https://shop.example"),
        ("http://shop.example:80", "http://shop.example"),
        ("http://localhost:8080", "http://localhost:8080"),
        ("https://shop.example/", "https://shop.example"),
    ],
)
def test_an_origin_is_reduced_to_scheme_host_and_non_default_port(given, expected):
    assert normalize_origin(given) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "*",
        "null",
        "",
        "shop.example",
        "//shop.example",
        "ftp://shop.example",
        "javascript:alert(1)",
        "https://",
        "https://shop.example/path",
        "https://shop.example?x=1",
        "https://shop.example#frag",
        "https://user@shop.example",
        "https://*.shop.example",
        "https://shop example",
    ],
)
def test_anything_that_is_not_a_plain_origin_is_rejected(bad):
    """A wildcard or a sloppy entry in a tenant's list must never widen who is allowed."""
    assert normalize_origin(bad) is None
