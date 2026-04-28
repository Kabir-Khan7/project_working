"""
models/transaction.py
---------------------
Core ledger row.

Stored in **double-entry** style — every transaction has a debit and credit
account, each with the same amount. We model it as a single row with both
account FKs to keep queries simple at the MVP stage.

Sensitive fields (party_name, memo) can later be encrypted at column level
via the AES helpers in core.security.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Transaction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_tx_org_date", "org_id", "txn_date"),
        Index("ix_tx_org_account", "org_id", "account_id"),
    )

    org_id: Mapped[str] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # ── Source tracking ───────────────────────────────────────────────────────
    ingestion_job_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_row_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # SHA-256 of the original row → idempotency

    # ── Core ledger fields ────────────────────────────────────────────────────
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    party_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)   # "debit" | "credit"

    # ── Categorisation ────────────────────────────────────────────────────────
    account_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_hint: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # confidence: 0.0–1.0 — how sure the categorizer was
    category_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    account: Mapped[Optional["Account"]] = relationship(  # noqa: F821
        "Account", back_populates="transactions"
    )
    ingestion_job: Mapped[Optional["IngestionJob"]] = relationship(  # noqa: F821
        "IngestionJob", back_populates="transactions"
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.txn_date} {self.direction} {self.amount} {self.currency}>"
