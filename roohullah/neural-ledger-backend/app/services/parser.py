"""
services/parser.py
------------------
Reads CSV / XLSX files into a normalised DataFrame.

Output schema (always):
    txn_date     pd.Timestamp
    description  str
    party_name   str | None
    reference    str | None
    amount       Decimal
    direction    "debit" | "credit"
    currency     str (default "PKR")

The parser is **forgiving** about column naming — it auto-maps common variants
(date / Date / TXN_DATE / posting date → txn_date, etc.).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterator, Optional

import pandas as pd


# ── Column aliases ────────────────────────────────────────────────────────────
COLUMN_ALIASES = {
    "txn_date": [
        "date", "txn_date", "transaction_date", "posting_date", "post_date",
        "value_date", "trans_date", "tarikh",
    ],
    "description": [
        "description", "desc", "narration", "memo", "details", "particulars",
        "remarks", "note",
    ],
    "party_name": [
        "party", "party_name", "vendor", "customer", "payee", "name",
        "supplier", "client",
    ],
    "reference": [
        "reference", "ref", "ref_no", "voucher", "voucher_no",
        "invoice", "invoice_no", "bill_no", "doc_no",
    ],
    "amount": [
        "amount", "amt", "total", "value", "transaction_amount",
    ],
    "debit": [
        "debit", "dr", "dr_amount", "out", "withdrawal", "paid",
    ],
    "credit": [
        "credit", "cr", "cr_amount", "in", "deposit", "received",
    ],
    "currency": [
        "currency", "ccy", "curr",
    ],
}


# ── Custom exceptions ─────────────────────────────────────────────────────────
class ParserError(Exception):
    pass


class UnsupportedFormatError(ParserError):
    pass


# ── DTO returned per parsed row ───────────────────────────────────────────────
@dataclass
class ParsedRow:
    txn_date: pd.Timestamp
    description: str
    amount: Decimal
    direction: str             # "debit" | "credit"
    party_name: Optional[str] = None
    reference: Optional[str] = None
    currency: str = "PKR"


# ── Public entry point ────────────────────────────────────────────────────────
def parse_file(*, content: bytes, filename: str) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse uploaded file content into a normalised DataFrame.

    Returns:
        (df, warnings)  — df has the canonical columns;
                          warnings list includes things like "skipped 3 empty rows".
    Raises:
        UnsupportedFormatError, ParserError
    """
    name = filename.lower()
    if name.endswith(".csv"):
        df = _read_csv(content)
    elif name.endswith((".xlsx", ".xls", ".xlsm")):
        df = _read_excel(content)
    else:
        raise UnsupportedFormatError(
            f"Unsupported file type: {filename}. Use .csv or .xlsx"
        )

    df, warnings = _normalise(df)
    return df, warnings


# ── Iterator → ParsedRow per validated row ────────────────────────────────────
def iter_rows(df: pd.DataFrame) -> Iterator[ParsedRow]:
    """
    Yields one ParsedRow per valid row. Skips rows that fail validation
    (caller decides what to do with the count).
    """
    for _, row in df.iterrows():
        try:
            yield _row_to_dto(row)
        except (ValueError, InvalidOperation, KeyError):
            continue


# ── Internal: file readers ────────────────────────────────────────────────────
def _read_csv(content: bytes) -> pd.DataFrame:
    # Try utf-8 first, fall back to latin-1
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ParserError("Unable to decode CSV — try saving as UTF-8")


def _read_excel(content: bytes) -> pd.DataFrame:
    # First sheet by default; later we can let user pick
    return pd.read_excel(io.BytesIO(content), engine="openpyxl")


# ── Internal: normalisation ───────────────────────────────────────────────────
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def _normalise(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Map heterogeneous column names → canonical schema.
    Drops rows missing required fields.
    """
    warnings: list[str] = []

    # 1. Slugify column names
    df = df.copy()
    df.columns = [_slug(c) for c in df.columns]

    # 2. Map aliases → canonical
    rename_map = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in df.columns and canonical not in df.columns:
                rename_map[alias] = canonical
                break
    df = df.rename(columns=rename_map)

    # 3. Required columns
    if "txn_date" not in df.columns:
        raise ParserError("Required column missing: date / txn_date")
    if "description" not in df.columns:
        raise ParserError("Required column missing: description / narration / memo")

    # 4. Derive amount + direction
    if "amount" not in df.columns:
        if "debit" in df.columns or "credit" in df.columns:
            debit = pd.to_numeric(df.get("debit", 0), errors="coerce").fillna(0)
            credit = pd.to_numeric(df.get("credit", 0), errors="coerce").fillna(0)
            df["amount"] = debit.where(debit != 0, credit)
            df["direction"] = ["debit" if d != 0 else "credit"
                                for d in debit]
        else:
            raise ParserError(
                "Need either 'amount' OR 'debit'/'credit' columns"
            )
    else:
        # amount column present; treat negatives as credits, positives as debits
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        df["direction"] = df["amount"].apply(
            lambda x: "credit" if (pd.notna(x) and x < 0) else "debit"
        )
        df["amount"] = df["amount"].abs()

    # 5. Date parsing — try ISO (YYYY-MM-DD) first, then day-first (DD/MM/YYYY)
    #    dayfirst=False avoids a pandas UserWarning when dates are already ISO.
    df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce", dayfirst=False)

    # 6. Drop unusable rows
    before = len(df)
    df = df.dropna(subset=["txn_date", "description", "amount"])
    df = df[df["amount"] > 0]
    skipped = before - len(df)
    if skipped:
        warnings.append(f"Skipped {skipped} rows with missing/invalid required fields")

    # 7. Currency default
    if "currency" not in df.columns:
        df["currency"] = "PKR"
    else:
        df["currency"] = df["currency"].fillna("PKR").astype(str).str.upper()

    # 8. Optional columns default
    for opt in ("party_name", "reference"):
        if opt not in df.columns:
            df[opt] = None

    keep = ["txn_date", "description", "party_name", "reference",
            "amount", "direction", "currency"]
    return df[keep].reset_index(drop=True), warnings


def _row_to_dto(row: pd.Series) -> ParsedRow:
    return ParsedRow(
        txn_date=row["txn_date"],
        description=str(row["description"]).strip(),
        amount=Decimal(str(row["amount"])).quantize(Decimal("0.01")),
        direction=row["direction"],
        party_name=(str(row["party_name"]).strip()
                    if pd.notna(row["party_name"]) else None),
        reference=(str(row["reference"]).strip()
                   if pd.notna(row["reference"]) else None),
        currency=str(row["currency"]).upper(),
    )
