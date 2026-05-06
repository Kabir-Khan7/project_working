"""
1.3.3 — Secure Data Boundary (Standalone Module)
--------------------------------------------------
Enforces the rule: "Raw data NEVER leaves the device."

This module acts as a gatekeeper. Before any data is sent to the cloud,
it passes through this boundary checker which:

    1. Classifies each field as LOCAL_ONLY or CLOUD_SAFE
    2. Blocks any payload that contains raw transaction data
    3. Allows only aggregated metadata through

Think of it like airport security:
    - Raw transactions = liquids over 100ml → BLOCKED
    - Aggregated metadata = boarding pass → ALLOWED

Dependencies:
    pip install pandas (only for DataFrame inspection)

Usage:
    from data_boundary import DataBoundary, BoundaryViolation

    boundary = DataBoundary()

    # This passes:
    boundary.validate_for_cloud({"totals": {"income": 50000}})

    # This gets BLOCKED:
    boundary.validate_for_cloud({"description": "Payment to Ali 0300-1234567"})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


# ── Classification ────────────────────────────────────────────────────────────
# Fields that contain raw personal/financial data — NEVER sync to cloud.
LOCAL_ONLY_FIELDS = frozenset({
    "description",
    "narration",
    "party_name",
    "payee",
    "vendor",
    "customer",
    "reference",
    "ref_no",
    "voucher_no",
    "invoice_no",
    "check_no",
    "account_number",
    "iban",
    "cnic",
    "phone",
    "email",
    "address",
    "password",
    "password_hash",
    "raw_text",
    "ocr_text",
})

# Fields that are safe to sync (aggregated/anonymized)
CLOUD_SAFE_FIELDS = frozenset({
    "totals",
    "averages",
    "trends",
    "categories",
    "top_parties",       # names only (no CNIC/phone)
    "transaction_count",
    "income",
    "expenses",
    "net",
    "pii_summary",
    "avg_transaction",
    "avg_income",
    "avg_expense",
    "month",
    "count",
    "total",
    "pii_types_detected",
    "flagged_columns",
    "rows_with_pii",
    "pii_percentage",
    "status",
    "rows_imported",
    "rows_skipped",
    "rows_failed",
    "rows_total",
    "file_sha256",
    "filename",
    "file_size_bytes",
    "mime_type",
    "created_at",
    "updated_at",
    "org_id",
})


# ── Exceptions ────────────────────────────────────────────────────────────────
class BoundaryViolation(Exception):
    """Raised when raw data is about to leave the device."""
    def __init__(self, blocked_fields: list[str], message: str = ""):
        self.blocked_fields = blocked_fields
        super().__init__(
            message or
            f"BLOCKED: These fields contain raw data and cannot leave the device: "
            f"{blocked_fields}"
        )


# ── Data Boundary Class ──────────────────────────────────────────────────────
@dataclass
class DataBoundary:
    """
    Gatekeeper that enforces local-vs-cloud data separation.

    Usage:
        boundary = DataBoundary()

        # Check if a payload is safe to sync
        report = boundary.classify(payload)
        # report.blocked = ["description", "party_name"]
        # report.allowed = ["totals", "averages"]

        # Strict mode: raises exception if unsafe
        boundary.validate_for_cloud(payload)  # raises BoundaryViolation

        # Filter mode: strip unsafe fields, return only safe ones
        safe_payload = boundary.filter_for_cloud(payload)
    """
    local_only: frozenset[str] = field(default_factory=lambda: LOCAL_ONLY_FIELDS)
    cloud_safe: frozenset[str] = field(default_factory=lambda: CLOUD_SAFE_FIELDS)

    def classify(self, payload: dict[str, Any]) -> "ClassificationReport":
        """
        Classify each field in the payload as LOCAL_ONLY or CLOUD_SAFE.
        """
        blocked: list[str] = []
        allowed: list[str] = []
        unknown: list[str] = []

        for key in payload.keys():
            key_lower = key.lower()
            if key_lower in self.local_only:
                blocked.append(key)
            elif key_lower in self.cloud_safe:
                allowed.append(key)
            else:
                # Unknown fields are treated as LOCAL_ONLY by default (safe side)
                unknown.append(key)

        return ClassificationReport(
            blocked=blocked,
            allowed=allowed,
            unknown=unknown,
            is_safe=len(blocked) == 0,
        )

    def validate_for_cloud(self, payload: dict[str, Any]) -> None:
        """
        Validate that a payload contains NO raw data.

        Raises BoundaryViolation if any LOCAL_ONLY fields are found.
        """
        report = self.classify(payload)
        if not report.is_safe:
            raise BoundaryViolation(blocked_fields=report.blocked)

    def filter_for_cloud(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Return a copy of the payload with LOCAL_ONLY fields stripped out.

        Use this when you want to "best effort" sync — send what's safe,
        drop what's not.
        """
        report = self.classify(payload)
        return {
            key: value
            for key, value in payload.items()
            if key not in report.blocked
        }

    def classify_dataframe(self, df: pd.DataFrame) -> "ClassificationReport":
        """
        Classify a DataFrame's columns (not its data, just column names).
        """
        payload = {col: None for col in df.columns}
        return self.classify(payload)


@dataclass
class ClassificationReport:
    """Result of classifying a payload's fields."""
    blocked: list[str]      # fields that must NOT leave the device
    allowed: list[str]      # fields safe for cloud sync
    unknown: list[str]      # fields not in either list (treated as blocked)
    is_safe: bool           # True if no blocked fields

    def summary(self) -> str:
        if self.is_safe:
            return f"SAFE: All {len(self.allowed)} fields are cloud-safe."
        return (
            f"BLOCKED: {len(self.blocked)} field(s) contain raw data "
            f"({', '.join(self.blocked)}). "
            f"{len(self.allowed)} field(s) are safe."
        )


# ── CLI demo ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    boundary = DataBoundary()

    # Safe payload (aggregates only)
    safe = {
        "totals": {"income": 145000, "expenses": 58500},
        "averages": {"avg_transaction": 40700},
        "transaction_count": 5,
    }
    report = boundary.classify(safe)
    print(f"Safe payload: {report.summary()}")

    # Unsafe payload (contains raw data)
    unsafe = {
        "totals": {"income": 145000},
        "description": "Payment to Ali Khan via 0300-1234567",
        "party_name": "Ali Khan",
    }
    report = boundary.classify(unsafe)
    print(f"Unsafe payload: {report.summary()}")

    # Filter mode
    filtered = boundary.filter_for_cloud(unsafe)
    print(f"After filtering: {list(filtered.keys())}")
