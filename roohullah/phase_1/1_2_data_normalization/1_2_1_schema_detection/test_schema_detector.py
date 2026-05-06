"""
Tests for 1.2.1 Schema Detection
----------------------------------
Run: python -m pytest test_schema_detector.py -v
"""

import pandas as pd
import pytest
from schema_detector import (
    detect_and_normalize,
    detect_columns,
    SchemaDetectionError,
)


# ── Standard column names ─────────────────────────────────────────────────────
def test_standard_columns():
    df = pd.DataFrame({
        "date": ["2026-01-15", "2026-01-16"],
        "description": ["Rent", "Salary"],
        "amount": [50000, 200000],
    })
    result, warnings = detect_and_normalize(df)
    assert "txn_date" in result.columns
    assert "description" in result.columns
    assert "amount" in result.columns
    assert "direction" in result.columns
    assert len(result) == 2


# ── Pakistani-style column names ─────────────────────────────────────────────
def test_urdu_style_columns():
    """Pakistani SMEs often use 'tarikh' for date, 'narration' for description."""
    df = pd.DataFrame({
        "tarikh": ["2026-03-01"],
        "narration": ["Dukaan ka kiraya"],
        "debit": [35000],
        "credit": [0],
    })
    result, warnings = detect_and_normalize(df)
    assert len(result) == 1
    assert result.iloc[0]["direction"] == "debit"


def test_posting_date_alias():
    df = pd.DataFrame({
        "Posting Date": ["2026-04-10"],
        "Particulars": ["Fuel expense"],
        "Amount": [-2500],
    })
    result, _ = detect_and_normalize(df)
    assert pd.notna(result.iloc[0]["txn_date"])
    assert result.iloc[0]["direction"] == "credit"  # negative = credit
    assert float(result.iloc[0]["amount"]) == 2500   # abs value


# ── Debit / Credit merge ─────────────────────────────────────────────────────
def test_debit_credit_merge():
    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "description": ["Rent", "Sale", "Utility"],
        "debit": [50000, 0, 3500],
        "credit": [0, 80000, 0],
    })
    result, warnings = detect_and_normalize(df)
    assert len(result) == 3
    assert any("Merged debit/credit" in w for w in warnings)

    # Rent should be debit
    rent_row = result[result["description"] == "Rent"].iloc[0]
    assert rent_row["direction"] == "debit"
    assert float(rent_row["amount"]) == 50000

    # Sale should be credit
    sale_row = result[result["description"] == "Sale"].iloc[0]
    assert sale_row["direction"] == "credit"
    assert float(sale_row["amount"]) == 80000


# ── detect_columns() preview ─────────────────────────────────────────────────
def test_detect_columns_mapping():
    df = pd.DataFrame({
        "Trans Date": ["2026-01-01"],
        "Memo": ["Payment"],
        "Vendor": ["Ali"],
        "Invoice": ["INV-001"],
        "Amt": [5000],
    })
    mapping = detect_columns(df)
    assert mapping["txn_date"] == "Trans Date"
    assert mapping["description"] == "Memo"
    assert mapping["party_name"] == "Vendor"
    assert mapping["reference"] == "Invoice"
    assert mapping["amount"] == "Amt"


def test_detect_columns_missing():
    df = pd.DataFrame({"random_col": [1], "other": [2]})
    mapping = detect_columns(df)
    assert mapping["txn_date"] is None
    assert mapping["description"] is None


# ── Error handling ────────────────────────────────────────────────────────────
def test_missing_date_raises():
    df = pd.DataFrame({
        "description": ["Rent"],
        "amount": [50000],
    })
    with pytest.raises(SchemaDetectionError, match="txn_date"):
        detect_and_normalize(df)


def test_missing_description_raises():
    df = pd.DataFrame({
        "date": ["2026-01-01"],
        "amount": [50000],
    })
    with pytest.raises(SchemaDetectionError, match="description"):
        detect_and_normalize(df)


def test_no_amount_columns_raises():
    df = pd.DataFrame({
        "date": ["2026-01-01"],
        "description": ["Rent"],
    })
    with pytest.raises(SchemaDetectionError, match="amount"):
        detect_and_normalize(df)


# ── Edge cases ────────────────────────────────────────────────────────────────
def test_drops_rows_with_zero_amount():
    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02"],
        "description": ["Real", "Zero"],
        "amount": [5000, 0],
    })
    result, warnings = detect_and_normalize(df)
    assert len(result) == 1
    assert result.iloc[0]["description"] == "Real"


def test_default_currency_pkr():
    df = pd.DataFrame({
        "date": ["2026-01-01"],
        "description": ["Rent"],
        "amount": [50000],
    })
    result, _ = detect_and_normalize(df)
    assert result.iloc[0]["currency"] == "PKR"


def test_custom_default_currency():
    df = pd.DataFrame({
        "date": ["2026-01-01"],
        "description": ["Rent"],
        "amount": [50000],
    })
    result, _ = detect_and_normalize(df, default_currency="USD")
    assert result.iloc[0]["currency"] == "USD"


def test_optional_columns_default_none():
    df = pd.DataFrame({
        "date": ["2026-01-01"],
        "description": ["Rent"],
        "amount": [50000],
    })
    result, _ = detect_and_normalize(df)
    assert result.iloc[0]["party_name"] is None
    assert result.iloc[0]["reference"] is None
