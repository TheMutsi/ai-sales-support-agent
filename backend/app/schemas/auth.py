"""Wire contracts for the conversation, login and one-time-code endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.auth.scopes import IdentityLevel, Scope


class ConversationRequest(BaseModel):
    api_key: str = Field(min_length=1)


class LoginRequest(BaseModel):
    api_key: str = Field(min_length=1)
    token: str = Field(min_length=1)


class OtpRequest(BaseModel):
    api_key: str = Field(min_length=1)
    email: str = Field(min_length=1, max_length=254)


class OtpVerifyRequest(OtpRequest):
    # No minimum: a wrong or empty code is the same generic 401 as any other failure.
    code: str = Field(max_length=16)


class SessionResponse(BaseModel):
    """What a client gets back when it starts a conversation or logs in."""

    session_token: str
    conversation_id: uuid.UUID
    expires_at: datetime
    identity_level: IdentityLevel
    scopes: list[Scope]
