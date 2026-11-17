from typing import Annotated

from fastapi import Header, HTTPException

from app.auth.session import SessionClaims, SessionError, verify_session_token
from app.core.config import get_settings


def _unauthorized(code: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail={"code": code}, headers={"WWW-Authenticate": "Bearer"}
    )


def require_session(authorization: Annotated[str | None, Header()] = None) -> SessionClaims:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("missing_session")
    try:
        return verify_session_token(token.strip(), get_settings().session_signing_key)
    except SessionError as exc:
        raise _unauthorized(exc.code) from None


def optional_session(authorization: Annotated[str | None, Header()] = None) -> SessionClaims | None:
    try:
        return require_session(authorization)
    except HTTPException:
        return None
