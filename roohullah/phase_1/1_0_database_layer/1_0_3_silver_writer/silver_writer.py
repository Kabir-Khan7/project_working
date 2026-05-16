"""
Silver Writer — Normalises bronze_transactions rows into silver_transactions.

Part of the Medallion Architecture (Bronze → Silver → Gold) pipeline.
Reads pending rows from bronze_transactions, normalises them, applies PII masking,
and writes clean data to silver_transactions. Failed rows go to silver_quarantine.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProcessResult:
    """Result of a batch processing run."""

    rows_processed: int = 0
    rows_normalised: int = 0
    rows_quarantined: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

# Date formats to try in order
_DATE_FORMATS = [
    "%d/%m/%Y",      # DD/MM/YYYY
    "%Y-%m-%d",      # YYYY-MM-DD
    "%m/%d/%Y",      # MM/DD/YYYY
    "%d-%b-%Y",      # DD-MMM-YYYY (e.g. 01-Jan-2024)
    "%d-%m-%Y",      # DD-MM-YYYY
    "%Y/%m/%d",      # YYYY/MM/DD
    "%d %b %Y",      # DD MMM YYYY
    "%d %B %Y",      # DD Month YYYY
]


def parse_date(value: str) -> date | None:
    """Try to parse a date string using multiple common formats.

    Returns a date object on success, None on failure.
    """
    if not value or not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue

    return None


def parse_amount(value: str) -> float | None:
    """Parse a monetary amount string into a float.

    Handles: PKR prefix, Rs prefix, commas, parentheses (negative),
    leading/trailing whitespace.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    value = value.strip()
    if not value:
        return None

    # Check for parentheses indicating negative
    is_negative = False
    if value.startswith("(") and value.endswith(")"):
        is_negative = True
        value = value[1:-1].strip()

    # Check for explicit minus sign
    if value.startswith("-"):
        is_negative = True
        value = value[1:].strip()

    # Remove currency prefixes
    for prefix in ("PKR", "Rs.", "Rs", "pkr", "rs.", "rs"):
        if value.upper().startswith(prefix.upper()):
            value = value[len(prefix):].strip()
            break

    # Remove commas and spaces used as thousands separators
    value = value.replace(",", "").replace(" ", "")

    if not value:
        return None

    try:
        result = float(value)
        return -result if is_negative else result
    except (ValueError, TypeError):
        return None


def detect_language(text: str) -> str:
    """Detect whether text is English, Urdu, or mixed.

    Checks for characters in the Arabic/Urdu Unicode range (U+0600–U+06FF, U+0750–U+077F, U+FB50–U+FDFF, U+FE70–U+FEFF).
    Returns 'ur' if predominantly Urdu, 'mixed' if both, 'en' otherwise.
    """
    if not text or not isinstance(text, str):
        return "en"

    urdu_pattern = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
    ascii_alpha_pattern = re.compile(r"[a-zA-Z]")

    has_urdu = bool(urdu_pattern.search(text))
    has_english = bool(ascii_alpha_pattern.search(text))

    if has_urdu and has_english:
        return "mixed"
    elif has_urdu:
        return "ur"
    else:
        return "en"


# PII patterns
_CNIC_PATTERN = re.compile(r"\b\d{5}-\d{7}-\d\b")
_PHONE_PATTERN = re.compile(r"(\+92|0)\d{10}")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


def mask_pii(text: str) -> tuple[str, list[str]]:
    """Scan text for PII and mask it.

    Returns (masked_text, list_of_pii_types_found).
    PII types: 'cnic', 'phone', 'email'
    """
    if not text or not isinstance(text, str):
        return (text or "", [])

    pii_types: list[str] = []
    masked = text

    if _CNIC_PATTERN.search(masked):
        pii_types.append("cnic")
        masked = _CNIC_PATTERN.sub("*****-*******-*", masked)

    if _PHONE_PATTERN.search(masked):
        pii_types.append("phone")
        masked = _PHONE_PATTERN.sub("***PHONE***", masked)

    if _EMAIL_PATTERN.search(masked):
        pii_types.append("email")
        masked = _EMAIL_PATTERN.sub("***EMAIL***", masked)

    return (masked, pii_types)


def compute_fiscal_year(dt: date) -> str:
    """Compute Pakistani fiscal year (July–June).

    Example: August 2024 → '2024-2025', March 2025 → '2024-2025'.
    """
    if dt.month >= 7:
        return f"{dt.year}-{dt.year + 1}"
    else:
        return f"{dt.year - 1}-{dt.year}"


def compute_quality_score(row_data: dict) -> float:
    """Compute a quality score (0.0–1.0) for a processed row.

    Scoring:
      +0.3 if has valid date
      +0.3 if has amount (debit or credit)
      +0.2 if has description
      +0.1 if has vendor
      +0.1 if no PII found
    """
    score = 0.0

    if row_data.get("transaction_date"):
        score += 0.3

    if row_data.get("amount_debit") or row_data.get("amount_credit"):
        score += 0.3

    if row_data.get("description") and row_data["description"].strip():
        score += 0.2

    if row_data.get("vendor") and row_data["vendor"].strip():
        score += 0.1

    if not row_data.get("pii_types_found"):
        score += 0.1

    return round(score, 2)


# ---------------------------------------------------------------------------
# Column detection heuristics
# ---------------------------------------------------------------------------

_DATE_KEYS = {"date", "transaction_date", "txn_date", "trans_date", "posting_date", "value_date", "dated"}
_AMOUNT_KEYS = {"amount", "debit", "credit", "dr", "cr", "withdrawal", "deposit", "payment", "receipt"}
_DEBIT_KEYS = {"debit", "dr", "withdrawal", "payment", "amount_debit"}
_CREDIT_KEYS = {"credit", "cr", "deposit", "receipt", "amount_credit"}
_DESC_KEYS = {"description", "desc", "narration", "narrative", "details", "particulars", "memo", "remarks"}
_VENDOR_KEYS = {"vendor", "payee", "merchant", "party", "beneficiary", "sender", "receiver", "name"}


def _find_key(data: dict, candidates: set[str]) -> str | None:
    """Find first matching key (case-insensitive) in data dict."""
    lower_map = {k.lower().strip(): k for k in data.keys()}
    for candidate in candidates:
        if candidate in lower_map:
            return lower_map[candidate]
    return None


def _extract_field(data: dict, candidates: set[str]) -> str | None:
    """Extract first matching field value as string."""
    key = _find_key(data, candidates)
    if key is None:
        return None
    val = data[key]
    if val is None:
        return None
    return str(val).strip()


# ---------------------------------------------------------------------------
# SilverWriter class
# ---------------------------------------------------------------------------

class SilverWriter:
    """Normalises bronze_transactions rows into silver_transactions."""

    def process_batch(self, conn: Any, batch_id: str) -> ProcessResult:
        """Process all pending rows in a given batch.

        Args:
            conn: DuckDB connection.
            batch_id: The ingestion_batch_id to process.

        Returns:
            ProcessResult with counts and timing.
        """
        start_time = time.time()
        result = ProcessResult()

        # Fetch pending rows for this batch
        rows = conn.execute(
            """
            SELECT bronze_id, source_type, source_software, raw_content, raw_headers,
                   ingestion_batch_id
            FROM bronze_transactions
            WHERE ingestion_batch_id = ? AND processing_status = 'pending'
            """,
            [batch_id],
        ).fetchall()

        columns = ["bronze_id", "source_type", "source_software", "raw_content", "raw_headers", "ingestion_batch_id"]

        for row in rows:
            bronze_row = dict(zip(columns, row))
            result.rows_processed += 1
            try:
                status = self.process_row(conn, bronze_row)
                if status == "normalised":
                    result.rows_normalised += 1
                else:
                    result.rows_quarantined += 1
            except Exception as e:
                result.rows_quarantined += 1
                result.errors.append(f"bronze_id={bronze_row['bronze_id']}: {str(e)}")
                # Quarantine the failed row
                self._quarantine_row(
                    conn,
                    bronze_row["bronze_id"],
                    "processing_error",
                    bronze_row.get("raw_content", ""),
                    str(e),
                )
                # Update bronze status
                conn.execute(
                    "UPDATE bronze_transactions SET processing_status = 'quarantined' WHERE bronze_id = ?",
                    [bronze_row["bronze_id"]],
                )

        duration_ms = int((time.time() - start_time) * 1000)
        result.duration_ms = duration_ms

        # Write audit log
        self._write_audit_log(
            conn,
            operation="silver_write",
            source_layer="bronze",
            batch_id=batch_id,
            status="completed" if not result.errors else "completed_with_errors",
            rows_affected=result.rows_processed,
            error_detail="; ".join(result.errors) if result.errors else None,
            duration_ms=duration_ms,
        )

        return result

    def process_row(self, conn: Any, bronze_row: dict) -> str:
        """Process a single bronze row into silver or quarantine.

        Args:
            conn: DuckDB connection.
            bronze_row: Dict with keys: bronze_id, raw_content, etc.

        Returns:
            'normalised' or 'quarantined'
        """
        bronze_id = bronze_row["bronze_id"]
        raw_content = bronze_row.get("raw_content", "{}")

        # Parse raw_content JSON
        try:
            data = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError) as e:
            self._quarantine_row(conn, bronze_id, "invalid_json", raw_content, str(e))
            conn.execute(
                "UPDATE bronze_transactions SET processing_status = 'quarantined' WHERE bronze_id = ?",
                [bronze_id],
            )
            return "quarantined"

        if not isinstance(data, dict):
            self._quarantine_row(conn, bronze_id, "invalid_json_structure", raw_content, "raw_content is not a JSON object")
            conn.execute(
                "UPDATE bronze_transactions SET processing_status = 'quarantined' WHERE bronze_id = ?",
                [bronze_id],
            )
            return "quarantined"

        # Extract fields
        date_str = _extract_field(data, _DATE_KEYS)
        transaction_date = parse_date(date_str) if date_str else None

        # Amounts
        debit_str = _extract_field(data, _DEBIT_KEYS)
        credit_str = _extract_field(data, _CREDIT_KEYS)

        # If only generic "amount" key, try to figure out debit/credit
        if debit_str is None and credit_str is None:
            amount_str = _extract_field(data, {"amount"})
            if amount_str:
                amount_val = parse_amount(amount_str)
                if amount_val is not None:
                    if amount_val < 0:
                        debit_str = str(abs(amount_val))
                    else:
                        credit_str = amount_str

        amount_debit = parse_amount(debit_str) if debit_str else None
        amount_credit = parse_amount(credit_str) if credit_str else None

        # Ensure non-negative
        if amount_debit is not None:
            amount_debit = abs(amount_debit)
        if amount_credit is not None:
            amount_credit = abs(amount_credit)

        description = _extract_field(data, _DESC_KEYS) or ""
        vendor = _extract_field(data, _VENDOR_KEYS) or ""

        # Combine all text for language detection
        all_text = " ".join(str(v) for v in data.values() if v)
        language_detected = detect_language(all_text)

        # PII masking on description
        description_masked, pii_types = mask_pii(description)
        pii_masked = len(pii_types) > 0

        # Build row data for quality scoring
        row_data = {
            "transaction_date": transaction_date,
            "amount_debit": amount_debit or 0.0,
            "amount_credit": amount_credit or 0.0,
            "description": description,
            "vendor": vendor,
            "pii_types_found": pii_types,
        }

        quality_score = compute_quality_score(row_data)

        # Quarantine decision: quality < 0.3 OR no date
        if quality_score < 0.3 or transaction_date is None:
            reason_parts = []
            if transaction_date is None:
                reason_parts.append("date_parse_failed")
            if quality_score < 0.3:
                reason_parts.append(f"low_quality_score({quality_score})")
            reason = "; ".join(reason_parts)

            self._quarantine_row(conn, bronze_id, reason, raw_content, None)
            conn.execute(
                "UPDATE bronze_transactions SET processing_status = 'quarantined' WHERE bronze_id = ?",
                [bronze_id],
            )
            return "quarantined"

        # Compute derived fields
        year_month = transaction_date.strftime("%Y-%m") if transaction_date else None
        fiscal_year = compute_fiscal_year(transaction_date) if transaction_date else None

        # Write to silver_transactions
        silver_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO silver_transactions (
                silver_id, bronze_id, transaction_date, year_month, fiscal_year,
                description, description_masked, vendor, category,
                amount_debit, amount_credit, currency, language_detected,
                is_duplicate, pii_masked, pii_types_found, quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                silver_id,
                bronze_id,
                transaction_date,
                year_month,
                fiscal_year,
                description,
                description_masked,
                vendor,
                None,  # category — not determined at this stage
                amount_debit or 0.0,
                amount_credit or 0.0,
                "PKR",
                language_detected,
                False,
                pii_masked,
                ",".join(pii_types) if pii_types else None,
                quality_score,
            ],
        )

        # Update bronze status
        conn.execute(
            "UPDATE bronze_transactions SET processing_status = 'normalised' WHERE bronze_id = ?",
            [bronze_id],
        )

        return "normalised"

    def _quarantine_row(
        self,
        conn: Any,
        bronze_id: str,
        reason: str,
        raw_content: str | None,
        error_detail: str | None,
    ) -> None:
        """Insert a row into silver_quarantine."""
        quarantine_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO silver_quarantine (quarantine_id, bronze_id, reason, raw_content, error_detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            [quarantine_id, bronze_id, reason, raw_content, error_detail],
        )

    def _write_audit_log(
        self,
        conn: Any,
        operation: str,
        source_layer: str,
        batch_id: str | None,
        status: str,
        rows_affected: int,
        error_detail: str | None,
        duration_ms: int,
    ) -> None:
        """Insert an entry into the pipeline_audit_log."""
        log_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO pipeline_audit_log (
                log_id, operation, source_layer, batch_id, status,
                rows_affected, error_detail, duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [log_id, operation, source_layer, batch_id, status, rows_affected, error_detail, duration_ms],
        )
