"""
models/ingestion.py
-------------------
Tracks every file uploaded into the system.

Why we track jobs:
  - Idempotency: same file (same SHA-256) shouldn't be ingested twice
  - Auditability: who uploaded what, when, with what result
  - Async-friendly: status field lets us move to a queue later
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


JOB_STATUSES = ("pending", "processing", "completed", "failed", "duplicate")


class IngestionJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        # One file (by hash) per org cannot be ingested twice
        UniqueConstraint("org_id", "file_sha256", name="uq_ingestion_org_hash"),
    )

    org_id: Mapped[str] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    uploaded_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── File metadata ─────────────────────────────────────────────────────────
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # ── Processing state ──────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    rows_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Privacy Firewall (M13) ────────────────────────────────────────────────
    # JSON summary of PII detected during ingestion.
    # Example: {"rows_with_pii": 3, "pii_types_detected": ["PHONE", "CNIC"], ...}
    # Raw PII values are NEVER stored here — only aggregate metadata.
    pii_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    transactions: Mapped[List["Transaction"]] = relationship(  # noqa: F821
        "Transaction", back_populates="ingestion_job"
    )

    def __repr__(self) -> str:
        return f"<IngestionJob id={self.id} status={self.status} {self.rows_imported}/{self.rows_total}>"
