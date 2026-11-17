import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.auth.scopes import IdentityLevel, Scope
from app.schemas.orders import ORDER_ID_PATTERN

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=254,
        pattern=r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$",
    ),
]
OtpCode = Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]


class ConversationRequest(BaseModel):
    api_key: str = Field(min_length=1)


class LoginRequest(BaseModel):
    api_key: str = Field(min_length=1)
    token: str = Field(min_length=1)


class OtpRequest(BaseModel):
    api_key: str = Field(min_length=1)
    email: Email


class OtpVerifyRequest(OtpRequest):
    code: OtpCode


class OrderLookupRequest(BaseModel):
    api_key: str = Field(min_length=1)
    email: Email
    order_id: str = Field(pattern=ORDER_ID_PATTERN)


class SessionResponse(BaseModel):
    session_token: str
    conversation_id: uuid.UUID
    expires_at: datetime
    identity_level: IdentityLevel
    scopes: list[Scope]
