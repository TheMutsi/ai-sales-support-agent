"""Request dependencies shared by the routers."""

from typing import Annotated

from fastapi import Header, HTTPException

from app.auth.session import SessionClaims, SessionError, verify_session_token
from app.core.config import get_settings


def _unauthorized(code: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail={"code": code}, headers={"WWW-Authenticate": "Bearer"}
    )


def require_session(authorization: Annotated[str | None, Header()] = None) -> SessionClaims:
    """Authenticates a request from the `Authorization: Bearer <session>` header.

    The codes let a client react: `session_expired` means "log in again" (the
    widget silently asks the shop for a fresh token); the others mean the
    request can't be fixed by retrying."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("missing_session")
    try:
        return verify_session_token(token.strip(), get_settings().session_signing_key)
    except SessionError as exc:
        raise _unauthorized(exc.code) from None
