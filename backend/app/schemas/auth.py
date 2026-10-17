"""Wire contracts for `POST /api/auth/login`."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.auth.scopes import IdentityLevel, Scope


class LoginRequest(BaseModel):
    api_key: str = Field(min_length=1)
    token: str = Field(min_length=1)


class LoginResponse(BaseModel):
    session_token: str
    expires_at: datetime
    identity_level: IdentityLevel
    scopes: list[Scope]
