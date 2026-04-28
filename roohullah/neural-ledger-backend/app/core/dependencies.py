"""
dependencies.py
---------------
FastAPI dependency-injection helpers:
  - get_db         → async SQLAlchemy session
  - get_current_user → decoded JWT → User ORM object
  - require_org_member → ensures user belongs to org
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.org import OrgMember

bearer_scheme = HTTPBearer()


# ── Database session ──────────────────────────────────────────────────────────
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


DBSession = Annotated[AsyncSession, Depends(get_db)]


# ── Current user from JWT ─────────────────────────────────────────────────────
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: DBSession,
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if not user_id or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ── Org membership guard ──────────────────────────────────────────────────────
def require_org_member(role: str = "member"):
    """
    Usage:
        @router.get("/orgs/{org_id}/...")
        async def handler(org_id: str, user=CurrentUser,
                          _=Depends(require_org_member("admin"))):
    """
    async def _check(
        org_id: str,
        user: CurrentUser,
        db: DBSession,
    ):
        from sqlalchemy import select
        result = await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == user.id,
                OrgMember.is_active == True,
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            raise HTTPException(status_code=403, detail="Not a member of this organisation")
        if role == "admin" and member.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        return member
    return _check
