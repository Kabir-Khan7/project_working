"""
Tests for 1.3.2 Metadata Extraction
--------------------------------------
Run: python -m pytest test_metadata_extractor.py -v
"""

import pandas as pd
import pytest
from metadata_extractor import extract_metadata


def _sample_df():
    return pd.DataFrame({
        "txn_date": pd.to_datetime([
            "2026-01-05", "2026-01-15", "2026-01-20",
            "2026-02-05", "2026-02-10",
        ]),
        "description": ["Rent", "Sale A", "Utilities", "Sale B", "Internet"],
        "party_name": ["Landlord", "ABC Co", "WAPDA", "ABC Co", "PTCL"],
        "amount": [50000, 80000, 3500, 65000, 5000],
        "direction": ["debit", "credit", "debit", "credit", "debit"],
    })


# ── Totals ────────────────────────────────────────────────────────────────────
def test_totals_income():
    meta = extract_metadata(_sample_df())
    assert meta["totals"]["income"] == 145000  # 80000 + 65000


def test_totals_expenses():
    meta = extract_metadata(_sample_df())
    assert meta["totals"]["expenses"] == 58500  # 50000 + 3500 + 5000


def test_totals_net():
    meta = extract_metadata(_sample_df())
    assert meta["totals"]["net"] == 145000 - 58500


def test_totals_count():
    meta = extract_metadata(_sample_df())
    assert meta["totals"]["transaction_count"] == 5


# ── Averages ──────────────────────────────────────────────────────────────────
def test_avg_transaction():
    meta = extract_metadata(_sample_df())
    expected = (50000 + 80000 + 3500 + 65000 + 5000) / 5
    assert meta["averages"]["avg_transaction"] == pytest.approx(expected, abs=1)


def test_avg_income():
    meta = extract_metadata(_sample_df())
    expected = (80000 + 65000) / 2
    assert meta["averages"]["avg_income"] == pytest.approx(expected, abs=1)


def test_avg_expense():
    meta = extract_metadata(_sample_df())
    expected = (50000 + 3500 + 5000) / 3
    assert meta["averages"]["avg_expense"] == pytest.approx(expected, abs=1)


# ── Monthly Trends ────────────────────────────────────────────────────────────
def test_trends_has_two_months():
    meta = extract_metadata(_sample_df())
    assert len(meta["trends"]) == 2


def test_trends_sorted_chronologically():
    meta = extract_metadata(_sample_df())
    months = [t["month"] for t in meta["trends"]]
    assert months == sorted(months)


def test_january_trend():
    meta = extract_metadata(_sample_df())
    jan = [t for t in meta["trends"] if "2026-01" in t["month"]][0]
    assert jan["income"] == 80000
    assert jan["expenses"] == 53500  # 50000 + 3500
    assert jan["count"] == 3


# ── Top Parties ───────────────────────────────────────────────────────────────
def test_top_parties_sorted():
    meta = extract_metadata(_sample_df())
    parties = meta["top_parties"]
    assert len(parties) >= 1
    # ABC Co should be #1 (80000 + 65000 = 145000)
    assert parties[0]["name"] == "ABC Co"
    assert parties[0]["total"] == 145000
    assert parties[0]["count"] == 2


def test_top_parties_includes_all():
    meta = extract_metadata(_sample_df())
    names = [p["name"] for p in meta["top_parties"]]
    assert "Landlord" in names
    assert "WAPDA" in names
    assert "PTCL" in names


# ── Edge cases ────────────────────────────────────────────────────────────────
def test_empty_dataframe():
    df = pd.DataFrame(columns=["txn_date", "description", "amount", "direction"])
    meta = extract_metadata(df)
    assert meta["totals"]["transaction_count"] == 0
    assert meta["totals"]["income"] == 0
    assert meta["trends"] == []


def test_no_party_column():
    df = pd.DataFrame({
        "txn_date": ["2026-01-01"],
        "description": ["Rent"],
        "amount": [50000],
        "direction": ["debit"],
    })
    meta = extract_metadata(df)
    assert meta["top_parties"] == []


def test_no_category_column():
    meta = extract_metadata(_sample_df())
    assert meta["categories"] == []


def test_with_categories():
    df = _sample_df().copy()
    df["category_hint"] = ["Rent", "Sales", "Utilities", "Sales", "Internet"]
    meta = extract_metadata(df)
    assert len(meta["categories"]) >= 1
    cats = {c["category"] for c in meta["categories"]}
    assert "Sales" in cats
    assert "Rent" in cats


# ── Privacy check: no raw data in metadata ────────────────────────────────────
def test_metadata_contains_no_raw_descriptions():
    """The extracted metadata should NEVER contain raw transaction descriptions."""
    meta = extract_metadata(_sample_df())
    meta_str = str(meta)
    # These are real descriptions — they should NOT appear in aggregates
    assert "Rent" not in meta_str or "Rent" in str(meta.get("categories", []))
    # Party names only appear in the top_parties aggregate
    assert "totals" in meta
    assert "averages" in meta
