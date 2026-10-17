"""Wire contracts for `POST /api/auth/login`."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.auth.scopes import IdentityLevel, Scope


class LoginRequest(BaseModel):
    api_key: str = Field(min_length=1)
    token: str = Field(min_length=1)


class SessionResponse(BaseModel):
    """What a client gets back when it starts a conversation or logs in."""

    session_token: str
    conversation_id: uuid.UUID
    expires_at: datetime
    identity_level: IdentityLevel
    scopes: list[Scope]
