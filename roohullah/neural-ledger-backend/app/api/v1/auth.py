"""
api/v1/auth.py
--------------
Routes:
  POST /api/v1/auth/register   → create user account
  POST /api/v1/auth/login      → returns access + refresh tokens
  POST /api/v1/auth/refresh    → rotate access token
  GET  /api/v1/auth/me         → current user profile
  POST /api/v1/auth/logout     → (stateless; client drops tokens)
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.config import settings
from app.core.dependencies import CurrentUser, DBSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserMeResponse,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Register ──────────────────────────────────────────────────────────────────
@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(payload: RegisterRequest, db: DBSession):
    # Check duplicate email
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ── Login ─────────────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DBSession):
    result = await db.execute(select(User).where(User.email == payload.email))
    user: User | None = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Refresh ───────────────────────────────────────────────────────────────────
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest, db: DBSession):
    try:
        data = decode_token(payload.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    user = await db.get(User, data["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Me ────────────────────────────────────────────────────────────────────────
@router.get("/me", response_model=UserMeResponse)
async def get_me(user: CurrentUser):
    return user


# ── Logout (stateless) ────────────────────────────────────────────────────────
@router.post("/logout", status_code=204)
async def logout():
    """
    Stateless logout — client is responsible for deleting tokens.
    For token blacklisting, integrate Redis here later.
    """
    return
