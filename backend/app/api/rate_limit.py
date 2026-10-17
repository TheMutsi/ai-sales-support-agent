"""Fixed-window rate limiting, counted in Postgres.

In Postgres instead of process memory so the count is right behind a load balancer,
where each instance would otherwise allow the full limit. The cost is one upsert per
limited request, paid only on the endpoints a stranger can call and on the chat.

A fixed window lets a client send up to twice the limit across a boundary; for
abuse control that is fine, and it keeps the counter to one row per key and window.

Not here: Redis (nothing else in the app needs it yet) and a global per-tenant budget.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from app.api.deps import require_session
from app.auth.session import SessionClaims
from app.core.config import get_settings
from app.db.session import SessionLocal

# Windows that ended more than this long ago are deleted when a new window starts.
_KEEP = timedelta(days=1)

_UPSERT = text(
    """
    INSERT INTO rate_limit_counters (key, window_start, count)
    VALUES (:key, :window_start, 1)
    ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limit_counters.count + 1
    RETURNING count
    """
)


def hit(db, *, key: str, limit: int, window_seconds: int, now: datetime) -> int | None:
    """Counts one request. Returns `None` when it is allowed, or the seconds until the
    window ends when the limit is already used up."""
    epoch = int(now.timestamp())
    window_start_epoch = epoch - epoch % window_seconds
    window_start = datetime.fromtimestamp(window_start_epoch, UTC)
    count = db.execute(_UPSERT, {"key": key, "window_start": window_start}).scalar_one()
    if count == 1:
        db.execute(
            text("DELETE FROM rate_limit_counters WHERE window_start < :before"),
            {"before": now - _KEEP},
        )
    db.commit()
    if count <= limit:
        return None
    return max(1, math.ceil(window_start_epoch + window_seconds - now.timestamp()))


def client_ip(request: Request) -> str:
    """The caller's address. `X-Forwarded-For` is only believed for as many hops as there
    are trusted proxies, counted from the right: the left part is whatever the client
    wrote, and anyone can write anything there."""
    peer = request.client.host if request.client else "unknown"
    trusted = get_settings().trusted_proxy_count
    forwarded = request.headers.get("x-forwarded-for")
    if trusted <= 0 or not forwarded:
        return peer
    hops = [part.strip() for part in forwarded.split(",") if part.strip()]
    return hops[-trusted] if len(hops) >= trusted else peer


def _enforce(key: str, limit: int, window_seconds: int) -> None:
    with SessionLocal() as db:
        retry_after = hit(
            db, key=key, limit=limit, window_seconds=window_seconds, now=datetime.now(UTC)
        )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited"},
            headers={"Retry-After": str(retry_after)},
        )


def limit_by_ip(name: str, limit: int, window_seconds: int):
    """A dependency that refuses the request once this address used up `limit` calls to
    the `name` group within the window."""

    def dependency(request: Request) -> None:
        _enforce(f"{name}:ip:{client_ip(request)}", limit, window_seconds)

    return Depends(dependency)


def limit_by_conversation(name: str, limit: int, window_seconds: int):
    """The same, counted per conversation: a logged-in client behind a shared address
    must not be blocked by its neighbours, nor spend the model's budget unchecked."""

    def dependency(session: Annotated[SessionClaims, Depends(require_session)]) -> None:
        conversation: uuid.UUID = session.conversation_id
        _enforce(f"{name}:conv:{conversation}", limit, window_seconds)

    return Depends(dependency)
