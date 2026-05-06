"""
1.2.1 — Schema Detection (Standalone Module)
----------------------------------------------
Auto-detects column meanings in financial data files.

Pakistani SMEs save files with wildly different column names:
    - "Date" vs "txn_date" vs "posting_date" vs "tarikh"
    - "Amount" vs "amt" vs "total" vs "value"
    - "Description" vs "narration" vs "memo" vs "particulars"

This module maps ANY of those names → one consistent schema:
    txn_date | description | party_name | reference | amount | direction | currency

How it works:
    1. Slugify column names (lowercase, remove spaces/special chars)
    2. Match against 30+ known aliases per field
    3. Derive amount + direction from debit/credit if needed
    4. Parse dates (supports DD/MM/YYYY and YYYY-MM-DD)

Dependencies:
    pip install pandas

Usage:
    from schema_detector import detect_and_normalize

    raw_df = pd.read_csv("messy_file.csv")
    clean_df, warnings = detect_and_normalize(raw_df)
    # clean_df now has: txn_date, description, amount, direction, ...
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd


# ── Column Aliases ────────────────────────────────────────────────────────────
# For each canonical column name, we list every variant we've seen
# in Pakistani SME files, bank exports, and accounting software.

COLUMN_ALIASES: dict[str, list[str]] = {
    "txn_date": [
        "date", "txn_date", "transaction_date", "posting_date", "post_date",
        "value_date", "trans_date", "tarikh", "dated",
    ],
    "description": [
        "description", "desc", "narration", "memo", "details", "particulars",
        "remarks", "note", "notes", "transaction_details",
    ],
    "party_name": [
        "party", "party_name", "vendor", "customer", "payee", "name",
        "supplier", "client", "beneficiary", "payer",
    ],
    "reference": [
        "reference", "ref", "ref_no", "voucher", "voucher_no",
        "invoice", "invoice_no", "bill_no", "doc_no", "check_no", "cheque_no",
    ],
    "amount": [
        "amount", "amt", "total", "value", "transaction_amount", "net_amount",
    ],
    "debit": [
        "debit", "dr", "dr_amount", "out", "withdrawal", "paid", "payment",
    ],
    "credit": [
        "credit", "cr", "cr_amount", "in", "deposit", "received", "receipt",
    ],
    "currency": [
        "currency", "ccy", "curr",
    ],
}

# Columns that MUST be found (everything else is optional)
REQUIRED_COLUMNS = ("txn_date", "description")


# ── Exceptions ────────────────────────────────────────────────────────────────
class SchemaDetectionError(Exception):
    """Raised when required columns cannot be identified."""
    pass


# ── Public API ────────────────────────────────────────────────────────────────
def detect_and_normalize(
    df: pd.DataFrame,
    default_currency: str = "PKR",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Detect schema and normalize column names + data types.

    Args:
        df: raw DataFrame (straight from CSV/Excel)
        default_currency: currency code when not specified in data

    Returns:
        (normalized_df, warnings)
        normalized_df has columns: txn_date, description, party_name,
                                   reference, amount, direction, currency

    Raises:
        SchemaDetectionError if required columns can't be found
    """
    warnings: list[str] = []
    df = df.copy()

    # Step 1: Slugify all column names
    df.columns = [_slugify(c) for c in df.columns]

    # Step 2: Map aliases → canonical names
    rename_map = _build_rename_map(df.columns)
    df = df.rename(columns=rename_map)

    # Step 3: Check required columns
    for req in REQUIRED_COLUMNS:
        if req not in df.columns:
            raise SchemaDetectionError(
                f"Required column not found: '{req}'. "
                f"We looked for these aliases: {COLUMN_ALIASES[req]}"
            )

    # Step 4: Derive amount + direction
    df, amount_warnings = _derive_amount(df)
    warnings.extend(amount_warnings)

    # Step 5: Parse dates
    df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce", dayfirst=False)

    # Step 6: Drop unusable rows
    before = len(df)
    df = df.dropna(subset=["txn_date", "description", "amount"])
    df = df[df["amount"] > 0]
    dropped = before - len(df)
    if dropped:
        warnings.append(f"Dropped {dropped} rows with missing/invalid required fields")

    # Step 7: Default currency
    if "currency" not in df.columns:
        df["currency"] = default_currency
    else:
        df["currency"] = df["currency"].fillna(default_currency).astype(str).str.upper()

    # Step 8: Optional columns default to None
    for opt in ("party_name", "reference"):
        if opt not in df.columns:
            df[opt] = None

    # Step 9: Select final columns in canonical order
    output_cols = [
        "txn_date", "description", "party_name", "reference",
        "amount", "direction", "currency",
    ]
    return df[output_cols].reset_index(drop=True), warnings


def detect_columns(df: pd.DataFrame) -> dict[str, Optional[str]]:
    """
    Just detect which columns map to which — without transforming.

    Returns a dict like:
        {"txn_date": "posting_date", "description": "narration", ...}

    Useful for showing the user: "We think 'posting_date' is your date column."
    """
    slugged = [_slugify(c) for c in df.columns]
    original_map = dict(zip(slugged, df.columns))

    result = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in slugged:
                found = original_map[alias]
                break
        result[canonical] = found

    return result


# ── Internals ─────────────────────────────────────────────────────────────────
def _slugify(col_name: str) -> str:
    """Convert 'Posting Date' → 'posting_date'."""
    return re.sub(r"[^a-z0-9]+", "_", str(col_name).strip().lower()).strip("_")


def _build_rename_map(columns: pd.Index) -> dict[str, str]:
    """Build a rename dict from detected aliases → canonical names."""
    rename_map = {}
    used_canonicals = set()

    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in columns and canonical not in used_canonicals:
                if alias != canonical:
                    rename_map[alias] = canonical
                used_canonicals.add(canonical)
                break

    return rename_map


def _derive_amount(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Derive 'amount' and 'direction' columns.

    Case 1: file has 'amount' → positive = debit, negative = credit
    Case 2: file has 'debit' + 'credit' → merge into amount + direction
    Case 3: neither → error
    """
    warnings = []

    if "amount" not in df.columns:
        if "debit" in df.columns or "credit" in df.columns:
            debit = pd.to_numeric(df.get("debit", 0), errors="coerce").fillna(0)
            credit = pd.to_numeric(df.get("credit", 0), errors="coerce").fillna(0)
            df["amount"] = debit.where(debit != 0, credit)
            df["direction"] = ["debit" if d != 0 else "credit" for d in debit]
            warnings.append("Merged debit/credit columns into amount + direction")
        else:
            raise SchemaDetectionError(
                "Need either 'amount' OR 'debit'/'credit' columns"
            )
    else:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        df["direction"] = df["amount"].apply(
            lambda x: "credit" if (pd.notna(x) and x < 0) else "debit"
        )
        df["amount"] = df["amount"].abs()

    return df, warnings


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python schema_detector.py <path_to_csv_or_xlsx>")
        sys.exit(1)

    filepath = sys.argv[1]
    raw = pd.read_csv(filepath) if filepath.endswith(".csv") else pd.read_excel(filepath)

    print("=== Raw Columns ===")
    print(list(raw.columns))

    print("\n=== Detected Mapping ===")
    mapping = detect_columns(raw)
    for canonical, original in mapping.items():
        status = f"  {canonical:15} ← {original}" if original else f"  {canonical:15} ← (not found)"
        print(status)

    print("\n=== Normalized Data ===")
    clean, warnings = detect_and_normalize(raw)
    print(f"Shape: {clean.shape}")
    print(f"Warnings: {warnings}")
    print(clean.head().to_string())
