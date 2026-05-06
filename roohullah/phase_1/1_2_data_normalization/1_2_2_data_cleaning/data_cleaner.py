"""
1.2.2 — Data Cleaning (Standalone Module)
-------------------------------------------
Cleans financial data: removes duplicates, handles missing values,
normalizes currency formats.

Pipeline:
    Raw DataFrame → deduplicate → fill_missing → normalize_currency → Clean DataFrame

How deduplication works:
    We create a SHA-256 hash from each row's key fields (date, description,
    amount, party, reference). If two rows produce the same hash, the
    second one is a duplicate and gets removed.

Dependencies:
    pip install pandas

Usage:
    from data_cleaner import clean_dataframe

    clean_df, report = clean_dataframe(raw_df)
    print(report)  # {"duplicates_removed": 3, "missing_filled": 5, ...}
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


# ── Cleaning Report ──────────────────────────────────────────────────────────
@dataclass
class CleaningReport:
    """Tracks what the cleaning process did."""
    rows_before: int = 0
    rows_after: int = 0
    duplicates_removed: int = 0
    missing_descriptions_filled: int = 0
    missing_parties_filled: int = 0
    currency_normalized: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "duplicates_removed": self.duplicates_removed,
            "missing_descriptions_filled": self.missing_descriptions_filled,
            "missing_parties_filled": self.missing_parties_filled,
            "currency_normalized": self.currency_normalized,
            "warnings": self.warnings,
        }


# ── Public API ────────────────────────────────────────────────────────────────
def clean_dataframe(
    df: pd.DataFrame,
    dedupe: bool = True,
    fill_missing: bool = True,
    normalize_currency: bool = True,
) -> tuple[pd.DataFrame, CleaningReport]:
    """
    Clean a normalized financial DataFrame.

    Expects columns: txn_date, description, amount, direction,
                     party_name, reference, currency

    Args:
        df: normalized DataFrame (output of schema_detector)
        dedupe: remove duplicate rows?
        fill_missing: fill missing descriptions/parties?
        normalize_currency: standardize currency codes?

    Returns:
        (cleaned_df, report)
    """
    report = CleaningReport(rows_before=len(df))
    df = df.copy()

    if dedupe:
        df, dupes = remove_duplicates(df)
        report.duplicates_removed = dupes

    if fill_missing:
        df, desc_filled, party_filled = handle_missing_values(df)
        report.missing_descriptions_filled = desc_filled
        report.missing_parties_filled = party_filled

    if normalize_currency:
        df, curr_count = normalize_currencies(df)
        report.currency_normalized = curr_count

    report.rows_after = len(df)

    if report.duplicates_removed > 0:
        report.warnings.append(
            f"Removed {report.duplicates_removed} duplicate row(s)"
        )

    return df, report


# ── Deduplication ─────────────────────────────────────────────────────────────
def remove_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Remove duplicate rows based on a hash of key fields.

    Two rows are "the same" if they have the same date + description +
    amount + party + reference. We use SHA-256 hashing for fast comparison.

    Returns:
        (deduplicated_df, number_of_duplicates_removed)
    """
    hashes = df.apply(_row_hash, axis=1)
    mask = ~hashes.duplicated(keep="first")
    dupes = (~mask).sum()
    return df[mask].reset_index(drop=True), dupes


def _row_hash(row: pd.Series) -> str:
    """Create a SHA-256 fingerprint of a row's key fields."""
    payload = "|".join([
        str(row.get("txn_date", "")),
        str(row.get("description", "")).strip().lower(),
        f"{float(row.get('amount', 0)):.2f}",
        str(row.get("party_name", "")).strip().lower(),
        str(row.get("reference", "")).strip().lower(),
    ])
    return hashlib.sha256(payload.encode()).hexdigest()


# ── Missing Value Handling ────────────────────────────────────────────────────
def handle_missing_values(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    """
    Fill missing values in description and party_name.

    - description: filled with "No description" (can't be empty)
    - party_name: filled with "Unknown" (optional field, but helpful)

    Returns:
        (df, descriptions_filled_count, parties_filled_count)
    """
    desc_missing = df["description"].isna().sum() if "description" in df.columns else 0
    party_missing = df["party_name"].isna().sum() if "party_name" in df.columns else 0

    if "description" in df.columns:
        df["description"] = df["description"].fillna("No description")

    if "party_name" in df.columns:
        df["party_name"] = df["party_name"].fillna("Unknown")

    return df, int(desc_missing), int(party_missing)


# ── Currency Normalization ────────────────────────────────────────────────────
# Common misspellings and variants of currency codes
CURRENCY_MAP = {
    "PKR": "PKR", "RS": "PKR", "RS.": "PKR", "RUPEE": "PKR", "RUPEES": "PKR",
    "PAK": "PKR", "PK": "PKR",
    "USD": "USD", "US$": "USD", "DOLLAR": "USD", "DOLLARS": "USD", "$": "USD",
    "EUR": "EUR", "EURO": "EUR",
    "GBP": "GBP", "POUND": "GBP",
    "AED": "AED", "DIRHAM": "AED",
    "SAR": "SAR", "RIYAL": "SAR",
}


def normalize_currencies(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Normalize currency codes: "Rs" → "PKR", "Dollar" → "USD", etc.

    Returns:
        (df, number_of_values_normalized)
    """
    if "currency" not in df.columns:
        return df, 0

    original = df["currency"].copy()
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["currency"] = df["currency"].map(
        lambda x: CURRENCY_MAP.get(x, x)
    )

    changed = (original != df["currency"]).sum()
    return df, int(changed)


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Quick demo with sample data
    sample = pd.DataFrame({
        "txn_date": ["2026-01-15", "2026-01-15", "2026-01-16", "2026-01-17"],
        "description": ["Rent", "Rent", None, "Utilities"],
        "party_name": ["Landlord", "Landlord", None, "WAPDA"],
        "reference": [None, None, None, "BILL-001"],
        "amount": [50000, 50000, 10000, 3500],
        "direction": ["debit", "debit", "credit", "debit"],
        "currency": ["PKR", "Rs", "Rupees", "pkr"],
    })

    print("=== Before Cleaning ===")
    print(sample.to_string())

    clean, report = clean_dataframe(sample)

    print("\n=== After Cleaning ===")
    print(clean.to_string())

    print("\n=== Report ===")
    for k, v in report.to_dict().items():
        print(f"  {k}: {v}")
