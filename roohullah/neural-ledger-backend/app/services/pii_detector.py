"""
M13 — Privacy Firewall: PII Detector
--------------------------------------
Scans transaction rows for Personally Identifiable Information (PII)
using regex patterns. Runs 100% locally — no internet, no external API.

PII categories we detect (Pakistan-specific + universal):
  CNIC        → 42101-1234567-9
  PHONE       → 0300-1234567 / +92-300-1234567
  EMAIL       → someone@domain.com
  IBAN        → PK32ABCD0000000000000000
  ACCOUNT_NO  → 8–16 digit standalone number
  ADDRESS     → "House #", "Street", "Block", "Sector", etc.

Pipeline position:
  parse_file() → [PII SCAN HERE] → iter_rows() → DB persist

Usage:
    from app.services.pii_detector import scan_dataframe, scan_row, mask_row

    result = scan_row({"description": "Paid 0300-1234567", "party_name": "Ali"})
    if result.has_pii:
        masked = mask_row(row_dict, result)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


# ── Regex Patterns (Pakistan-aware) ──────────────────────────────────────────
#
# Each pattern is compiled once (fast). We test field values against each.
#
PATTERNS: dict[str, re.Pattern] = {
    # CNIC: 42101-1234567-9  (5 digits, dash, 7 digits, dash, 1 digit)
    "CNIC": re.compile(r"\b\d{5}-\d{7}-\d\b"),

    # Pakistani mobile: 0300-1234567 / +923001234567 / 03001234567
    "PHONE": re.compile(
        r"(?<!\d)"
        r"(\+92|0092|92)?[-.\s]?(3\d{2})[-.\s]?\d{7}"
        r"|"
        r"\b0\d{2,3}[-.\s]?\d{6,7}\b"
    ),

    # Email address
    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    ),

    # Pakistani IBAN: PK + 2 digits + 4 letters + 16 digits
    "IBAN": re.compile(r"\bPK\d{2}[A-Z]{4}\d{16}\b"),

    # Plain bank account number (8–16 standalone digits)
    # Note: we skip 1–7 digit numbers to avoid false positives on amounts
    "ACCOUNT_NO": re.compile(r"(?<!\d)\d{8,16}(?!\d)"),

    # Address keywords (English + common Urdu-transliterated)
    "ADDRESS": re.compile(
        r"\b(house|h\.?\s*no\.?|street|st\.|block|sector|phase|plot|"
        r"flat|floor|apartment|apt\.?|road|rd\.|avenue|ave\.|lane|"
        r"gali|mohalla|muhalla|locality|colony|town|city)\b",
        re.IGNORECASE,
    ),
}

# Fields in a transaction row that could contain PII
PII_CANDIDATE_FIELDS = ("description", "party_name", "reference")


# ── Data Classes (tiny objects to hold scan results) ─────────────────────────
@dataclass
class PIIMatch:
    """One detected PII hit."""
    pii_type: str   # e.g. "PHONE"
    original: str   # the actual matched text
    token: str      # replacement token, e.g. "[PHONE_1]"
    field: str      # which column this came from


@dataclass
class PIIScanResult:
    """Result of scanning one row."""
    has_pii: bool
    matches: list[PIIMatch] = field(default_factory=list)
    flagged_fields: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """JSON-serializable dict, safe to store in the DB."""
        return {
            "has_pii": self.has_pii,
            "flagged_fields": self.flagged_fields,
            "pii_types_found": sorted({m.pii_type for m in self.matches}),
            "total_redactions": len(self.matches),
        }


# ── Row-level scan ────────────────────────────────────────────────────────────
def scan_row(row_dict: dict[str, Any]) -> PIIScanResult:
    """
    Scan one transaction row for PII.

    Args:
        row_dict: dict with keys like "description", "party_name", "reference"

    Returns:
        PIIScanResult with matches and flagged fields
    """
    matches: list[PIIMatch] = []
    flagged_fields: list[str] = []
    counters: dict[str, int] = {}

    for field_name in PII_CANDIDATE_FIELDS:
        value = row_dict.get(field_name)
        if not value or not isinstance(value, str):
            continue

        field_was_flagged = False

        for pii_type, pattern in PATTERNS.items():
            for m in pattern.finditer(value):
                matched_text = m.group().strip()
                if not matched_text:
                    continue

                counters[pii_type] = counters.get(pii_type, 0) + 1
                token = f"[{pii_type}_{counters[pii_type]}]"

                matches.append(PIIMatch(
                    pii_type=pii_type,
                    original=matched_text,
                    token=token,
                    field=field_name,
                ))
                field_was_flagged = True

        if field_was_flagged and field_name not in flagged_fields:
            flagged_fields.append(field_name)

    return PIIScanResult(
        has_pii=bool(matches),
        matches=matches,
        flagged_fields=flagged_fields,
    )


# ── Row masking ───────────────────────────────────────────────────────────────
def mask_row(row_dict: dict[str, Any], scan: PIIScanResult) -> dict[str, Any]:
    """
    Return a *copy* of row_dict with PII replaced by tokens.

    Example:
        input:  {"description": "Paid 0300-1234567 for office"}
        output: {"description": "Paid [PHONE_1] for office"}

    Original row_dict is NOT modified (immutable pattern).
    """
    masked = dict(row_dict)

    for match in scan.matches:
        current_val = masked.get(match.field)
        if current_val and isinstance(current_val, str):
            masked[match.field] = current_val.replace(match.original, match.token)

    return masked


# ── DataFrame-level scan (for IngestionJob summary) ──────────────────────────
def scan_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """
    Scan all rows in a parsed DataFrame and return an aggregate PII summary.
    This summary is stored in the IngestionJob.pii_summary column.

    Returns a dict like:
        {
            "total_rows_scanned": 100,
            "rows_with_pii": 12,
            "pii_percentage": 12.0,
            "pii_types_detected": ["CNIC", "PHONE"],
            "flagged_columns": ["description", "party_name"],
        }
    """
    total_rows = len(df)
    rows_with_pii = 0
    all_types: set[str] = set()
    flagged_cols: set[str] = set()

    for _, row in df.iterrows():
        row_dict = {
            "description": row.get("description"),
            "party_name":  row.get("party_name"),
            "reference":   row.get("reference"),
        }
        result = scan_row(row_dict)
        if result.has_pii:
            rows_with_pii += 1
            all_types.update(m.pii_type for m in result.matches)
            flagged_cols.update(result.flagged_fields)

    return {
        "total_rows_scanned": total_rows,
        "rows_with_pii": rows_with_pii,
        "pii_percentage": round(rows_with_pii / total_rows * 100, 1) if total_rows else 0,
        "pii_types_detected": sorted(all_types),
        "flagged_columns": sorted(flagged_cols),
    }
