from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import optional_session
from app.auth.login import LoginError, login_with_store_token, start_conversation
from app.auth.session import SessionClaims
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import ConversationRequest, LoginRequest, SessionResponse

router = APIRouter()


@router.post("/conversations", response_model=SessionResponse)
def new_conversation(
    request: ConversationRequest, db: Annotated[Session, Depends(get_db)]
) -> SessionResponse:
    """Starts an anonymous conversation and returns a session for it."""
    settings = get_settings()
    try:
        return start_conversation(
            db,
            api_key=request.api_key,
            session_key=settings.session_signing_key,
            session_ttl=timedelta(seconds=settings.session_ttl_seconds),
        )
    except LoginError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None


@router.post("/auth/login", response_model=SessionResponse)
def login(
    request: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[SessionClaims | None, Depends(optional_session)],
) -> SessionResponse:
    """`current` is the caller's present session, if any. Its conversation is continued
    when usable; an expired or invalid one is simply ignored."""
    settings = get_settings()
    try:
        return login_with_store_token(
            db,
            api_key=request.api_key,
            token=request.token,
            conversation_id=current.conversation_id if current else None,
            session_key=settings.session_signing_key,
            session_ttl=timedelta(seconds=settings.session_ttl_seconds),
        )
    except LoginError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None
