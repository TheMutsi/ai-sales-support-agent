"""What counts as a browser origin, for the per-tenant list of pages allowed to use a key.

Strict by design: an entry is exactly scheme, host and (non-default) port, so a typo can
never widen who is allowed. No wildcards: a shop lists the pages its widget runs on.
"""

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_origin(value: object) -> str | None:
    """`https://Shop.Example:443/` -> `https://shop.example`; `None` when it is not a plain origin."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or "*" in candidate or any(ch.isspace() for ch in candidate):
        return None
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/"):
        return None
    host = parts.hostname.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"
