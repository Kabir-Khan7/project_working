"""
models/org.py
-------------
Organisation + membership tables.

Organisation:
  - id, name, slug (URL-safe, unique)
  - industry      : e.g. "retail", "manufacturing"
  - country       : default "PK"
  - currency      : default "PKR"
  - is_active     : soft delete
  - plan          : "free" | "starter" | "pro"
  - plan_expires_at

OrgMember (join table):
  - org_id  FK → organisations
  - user_id FK → users
  - role    : "admin" | "member" | "viewer"
  - is_active
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Organisation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(10), default="PK", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    plan: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
    plan_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    members: Mapped[List["OrgMember"]] = relationship(
        "OrgMember", back_populates="org", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Organisation id={self.id} slug={self.slug}>"


class OrgMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_user"),
    )

    org_id: Mapped[str] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    org: Mapped["Organisation"] = relationship("Organisation", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")

    def __repr__(self) -> str:
        return f"<OrgMember user={self.user_id} org={self.org_id} role={self.role}>"
