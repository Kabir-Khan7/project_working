"""
Tests for 1.2.2 Data Cleaning
-------------------------------
Run: python -m pytest test_data_cleaner.py -v
"""

import pandas as pd
import pytest
from data_cleaner import (
    clean_dataframe,
    remove_duplicates,
    handle_missing_values,
    normalize_currencies,
)


def _sample_df():
    return pd.DataFrame({
        "txn_date": ["2026-01-15", "2026-01-16", "2026-01-17"],
        "description": ["Rent", "Salary", "Utilities"],
        "party_name": ["Landlord", "Self", "WAPDA"],
        "reference": [None, None, "BILL-001"],
        "amount": [50000, 200000, 3500],
        "direction": ["debit", "credit", "debit"],
        "currency": ["PKR", "PKR", "PKR"],
    })


# ── Deduplication ─────────────────────────────────────────────────────────────
def test_remove_exact_duplicates():
    df = pd.DataFrame({
        "txn_date": ["2026-01-15", "2026-01-15"],
        "description": ["Rent", "Rent"],
        "amount": [50000, 50000],
        "party_name": ["Landlord", "Landlord"],
        "reference": [None, None],
    })
    result, dupes = remove_duplicates(df)
    assert dupes == 1
    assert len(result) == 1


def test_keep_different_rows():
    df = _sample_df()
    result, dupes = remove_duplicates(df)
    assert dupes == 0
    assert len(result) == 3


def test_case_insensitive_dedupe():
    """'rent' and 'Rent' should be treated as the same."""
    df = pd.DataFrame({
        "txn_date": ["2026-01-15", "2026-01-15"],
        "description": ["Rent", "rent"],
        "amount": [50000, 50000],
        "party_name": ["Landlord", "landlord"],
        "reference": [None, None],
    })
    result, dupes = remove_duplicates(df)
    assert dupes == 1


# ── Missing Values ────────────────────────────────────────────────────────────
def test_fill_missing_description():
    df = pd.DataFrame({
        "description": ["Rent", None, "Sale"],
        "party_name": ["A", "B", "C"],
    })
    result, desc_filled, _ = handle_missing_values(df)
    assert desc_filled == 1
    assert result.iloc[1]["description"] == "No description"


def test_fill_missing_party():
    df = pd.DataFrame({
        "description": ["Rent"],
        "party_name": [None],
    })
    result, _, party_filled = handle_missing_values(df)
    assert party_filled == 1
    assert result.iloc[0]["party_name"] == "Unknown"


def test_no_missing_no_change():
    df = _sample_df()
    _, desc_filled, party_filled = handle_missing_values(df)
    assert desc_filled == 0
    assert party_filled == 0


# ── Currency Normalization ────────────────────────────────────────────────────
def test_rs_to_pkr():
    df = pd.DataFrame({"currency": ["Rs", "RS.", "Rupees"]})
    result, count = normalize_currencies(df)
    assert all(result["currency"] == "PKR")
    assert count == 3


def test_dollar_to_usd():
    df = pd.DataFrame({"currency": ["Dollar", "US$", "$"]})
    result, count = normalize_currencies(df)
    assert all(result["currency"] == "USD")


def test_already_normalized():
    df = pd.DataFrame({"currency": ["PKR", "PKR"]})
    result, count = normalize_currencies(df)
    assert count == 0  # no changes needed


def test_no_currency_column():
    df = pd.DataFrame({"description": ["Rent"]})
    result, count = normalize_currencies(df)
    assert count == 0


# ── Full Pipeline ─────────────────────────────────────────────────────────────
def test_full_cleaning_pipeline():
    df = pd.DataFrame({
        "txn_date": ["2026-01-15", "2026-01-15", "2026-01-16"],
        "description": ["Rent", "Rent", None],
        "party_name": ["Landlord", "Landlord", None],
        "reference": [None, None, None],
        "amount": [50000, 50000, 10000],
        "direction": ["debit", "debit", "credit"],
        "currency": ["Rs", "Rs", "Rupees"],
    })
    result, report = clean_dataframe(df)

    assert report.rows_before == 3
    assert report.duplicates_removed == 1
    assert report.missing_descriptions_filled >= 1
    assert report.rows_after == 2
    assert all(result["currency"] == "PKR")


def test_report_to_dict():
    df = _sample_df()
    _, report = clean_dataframe(df)
    d = report.to_dict()
    assert isinstance(d, dict)
    assert "duplicates_removed" in d
    assert "warnings" in d
