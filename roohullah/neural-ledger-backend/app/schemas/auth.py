"""
schemas/auth.py
---------------
Pydantic v2 schemas for auth endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Register ──────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v


class RegisterResponse(BaseModel):
    id: str
    email: str
    full_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Login ─────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower().strip()


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int       # seconds


# ── Refresh ───────────────────────────────────────────────────────────────────
class RefreshRequest(BaseModel):
    refresh_token: str


# ── Current user (me) ─────────────────────────────────────────────────────────
class UserMeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    is_verified: bool
    last_login: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
