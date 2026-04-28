"""
models/account.py
-----------------
Chart of Accounts for an organisation.

Categories follow standard double-entry bookkeeping:
    asset, liability, equity, revenue, expense
"""

from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")


class Account(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_account_org_code"),
    )

    org_id: Mapped[str] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True, nullable=False
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)        # e.g. "1010"
    name: Mapped[str] = mapped_column(String(200), nullable=False)       # "Cash in Hand"
    type: Mapped[str] = mapped_column(String(20), nullable=False)        # asset / expense / ...
    parent_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── relationships ─────────────────────────────────────────────────────────
    transactions: Mapped[List["Transaction"]] = relationship(  # noqa: F821
        "Transaction", back_populates="account"
    )

    def __repr__(self) -> str:
        return f"<Account {self.code} {self.name} ({self.type})>"
