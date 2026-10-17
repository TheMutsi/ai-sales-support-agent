from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.login import LoginError, login_with_store_token
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    settings = get_settings()
    try:
        return login_with_store_token(
            db,
            api_key=request.api_key,
            token=request.token,
            session_key=settings.session_signing_key,
            session_ttl=timedelta(seconds=settings.session_ttl_seconds),
        )
    except LoginError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None
