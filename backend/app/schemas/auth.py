"""Wire contracts for the conversation, login and one-time-code endpoints."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.auth.scopes import IdentityLevel, Scope

# Strict on purpose: these arrive from strangers and end up in a query and a log line. No
# validator library, so the rule is the one written here: a plain local part, a dotted
# domain, ASCII only. `[0-9]` and not `\\d`, which would also accept other scripts' digits.
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
    # Malformed is a 422, since its shape reveals nothing about accounts; a well-formed but
    # wrong code is the same generic 401 as every other failure.
    code: OtpCode


class SessionResponse(BaseModel):
    """What a client gets back when it starts a conversation or logs in."""

    session_token: str
    conversation_id: uuid.UUID
    expires_at: datetime
    identity_level: IdentityLevel
    scopes: list[Scope]
