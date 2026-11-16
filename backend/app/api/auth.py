from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import optional_session
from app.api.origins import check_origin_for_api_key
from app.api.rate_limit import limit_by_ip
from app.auth.login import (
    LoginError,
    find_tenant_id,
    login_with_order,
    login_with_otp,
    login_with_store_token,
    send_otp,
    start_conversation,
)
from app.auth.otp import OtpError
from app.auth.otp_sender import sender_for_tenant
from app.auth.session import SessionClaims
from app.core.config import get_settings
from app.db.session import get_db
from app.orders.factory import get_order_source
from app.orders.source import OrderSource
from app.schemas.auth import (
    ConversationRequest,
    LoginRequest,
    OrderLookupRequest,
    OtpRequest,
    OtpVerifyRequest,
    SessionResponse,
)

router = APIRouter()


@router.post(
    "/conversations",
    response_model=SessionResponse,
    dependencies=[limit_by_ip("conversations", limit=20, window_seconds=3600)],
)
def new_conversation(
    request: ConversationRequest, http: Request, db: Annotated[Session, Depends(get_db)]
) -> SessionResponse:
    check_origin_for_api_key(http, request.api_key)
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


@router.post(
    "/auth/login",
    response_model=SessionResponse,
    dependencies=[limit_by_ip("login", limit=30, window_seconds=600)],
)
def login(
    request: LoginRequest,
    http: Request,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[SessionClaims | None, Depends(optional_session)],
) -> SessionResponse:
    check_origin_for_api_key(http, request.api_key)
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


@router.post(
    "/auth/otp/request",
    status_code=202,
    dependencies=[limit_by_ip("otp_request", limit=10, window_seconds=3600)],
)
def otp_request(
    request: OtpRequest,
    http: Request,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[SessionClaims | None, Depends(optional_session)],
) -> None:
    check_origin_for_api_key(http, request.api_key)
    settings = get_settings()
    send_otp(
        db,
        api_key=request.api_key,
        email=request.email,
        sender_for=sender_for_tenant(settings, db),
        key=settings.session_signing_key,
        conversation_id=current.conversation_id if current else None,
    )


@router.post(
    "/auth/otp/verify",
    response_model=SessionResponse,
    dependencies=[limit_by_ip("otp_verify", limit=20, window_seconds=3600)],
)
def otp_verify(
    request: OtpVerifyRequest,
    http: Request,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[SessionClaims | None, Depends(optional_session)],
) -> SessionResponse:
    check_origin_for_api_key(http, request.api_key)
    settings = get_settings()
    try:
        return login_with_otp(
            db,
            api_key=request.api_key,
            email=request.email,
            code=request.code,
            conversation_id=current.conversation_id if current else None,
            session_key=settings.session_signing_key,
            session_ttl=timedelta(seconds=settings.session_ttl_seconds),
        )
    except OtpError as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code}) from None


@router.post(
    "/auth/order-lookup",
    response_model=SessionResponse,
    dependencies=[limit_by_ip("order_lookup", limit=20, window_seconds=3600)],
)
async def order_lookup(
    request: OrderLookupRequest,
    http: Request,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[SessionClaims | None, Depends(optional_session)],
    orders: Annotated[OrderSource, Depends(get_order_source)],
) -> SessionResponse:
    await run_in_threadpool(check_origin_for_api_key, http, request.api_key)
    settings = get_settings()
    tenant_id = await run_in_threadpool(find_tenant_id, db, request.api_key)
    await run_in_threadpool(db.rollback)
    order = (
        await orders.get_order(tenant_id=tenant_id, order_id=request.order_id)
        if tenant_id is not None
        else None
    )
    try:
        return await run_in_threadpool(
            lambda: login_with_order(
                db,
                api_key=request.api_key,
                email=request.email,
                order_id=request.order_id,
                order=order,
                conversation_id=current.conversation_id if current else None,
                session_key=settings.session_signing_key,
                session_ttl=timedelta(seconds=settings.session_ttl_seconds),
            )
        )
    except LoginError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None
