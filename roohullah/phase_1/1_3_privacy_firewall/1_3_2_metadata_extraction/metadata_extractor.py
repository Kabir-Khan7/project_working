"""
1.3.2 — Metadata Extraction (Standalone Module)
-------------------------------------------------
Converts raw financial data → summarized signals (aggregates).

This is the PRIVACY bridge: raw transactions stay on the user's device,
but these aggregated insights CAN be safely synced to the cloud because
they contain NO personally identifiable information.

What gets extracted:
    - Totals (total income, total expenses, net)
    - Averages (average transaction size)
    - Trends (monthly income/expense over time)
    - Category breakdown (if categories are assigned)
    - Top parties by transaction volume

Dependencies:
    pip install pandas

Usage:
    from metadata_extractor import extract_metadata

    metadata = extract_metadata(df)
    # metadata is a dict of pure numbers — safe to sync to cloud
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def extract_metadata(
    df: pd.DataFrame,
    date_col: str = "txn_date",
    amount_col: str = "amount",
    direction_col: str = "direction",
    party_col: str = "party_name",
    category_col: str = "category_hint",
) -> dict[str, Any]:
    """
    Extract aggregated metadata from a transaction DataFrame.

    Args:
        df: normalized DataFrame with txn_date, amount, direction, etc.

    Returns:
        dict with:
            totals:     {income, expenses, net, count}
            averages:   {avg_transaction, avg_income, avg_expense}
            trends:     [{month: "2026-01", income: X, expenses: Y}, ...]
            top_parties: [{name: "ABC Co", total: 150000, count: 5}, ...]
            categories: [{category: "Rent", total: 50000, count: 1}, ...]
    """
    result: dict[str, Any] = {}

    # ── Totals ────────────────────────────────────────────────────────────────
    result["totals"] = _extract_totals(df, amount_col, direction_col)

    # ── Averages ──────────────────────────────────────────────────────────────
    result["averages"] = _extract_averages(df, amount_col, direction_col)

    # ── Monthly Trends ────────────────────────────────────────────────────────
    result["trends"] = _extract_monthly_trends(df, date_col, amount_col, direction_col)

    # ── Top Parties ───────────────────────────────────────────────────────────
    if party_col in df.columns:
        result["top_parties"] = _extract_top_parties(df, party_col, amount_col)
    else:
        result["top_parties"] = []

    # ── Category Breakdown ────────────────────────────────────────────────────
    if category_col in df.columns and df[category_col].notna().any():
        result["categories"] = _extract_categories(df, category_col, amount_col)
    else:
        result["categories"] = []

    return result


# ── Internal Extractors ───────────────────────────────────────────────────────

def _extract_totals(
    df: pd.DataFrame, amount_col: str, direction_col: str
) -> dict[str, Any]:
    """Total income, total expenses, net balance, transaction count."""
    if direction_col not in df.columns:
        total = float(df[amount_col].sum())
        return {
            "income": 0.0,
            "expenses": total,
            "net": -total,
            "transaction_count": len(df),
        }

    credits = df[df[direction_col] == "credit"]
    debits = df[df[direction_col] == "debit"]

    income = float(credits[amount_col].sum()) if len(credits) else 0.0
    expenses = float(debits[amount_col].sum()) if len(debits) else 0.0

    return {
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "net": round(income - expenses, 2),
        "transaction_count": len(df),
    }


def _extract_averages(
    df: pd.DataFrame, amount_col: str, direction_col: str
) -> dict[str, float]:
    """Average transaction sizes."""
    avg_all = float(df[amount_col].mean()) if len(df) else 0.0

    avg_income = 0.0
    avg_expense = 0.0

    if direction_col in df.columns:
        credits = df[df[direction_col] == "credit"]
        debits = df[df[direction_col] == "debit"]
        avg_income = float(credits[amount_col].mean()) if len(credits) else 0.0
        avg_expense = float(debits[amount_col].mean()) if len(debits) else 0.0

    return {
        "avg_transaction": round(avg_all, 2),
        "avg_income": round(avg_income, 2),
        "avg_expense": round(avg_expense, 2),
    }


def _extract_monthly_trends(
    df: pd.DataFrame,
    date_col: str,
    amount_col: str,
    direction_col: str,
) -> list[dict[str, Any]]:
    """Monthly income/expense trend over time."""
    if date_col not in df.columns:
        return []

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])

    if len(df) == 0:
        return []

    df["_month"] = df[date_col].dt.to_period("M").astype(str)

    trends = []
    for month, group in df.groupby("_month"):
        if direction_col in group.columns:
            income = float(group[group[direction_col] == "credit"][amount_col].sum())
            expenses = float(group[group[direction_col] == "debit"][amount_col].sum())
        else:
            income = 0.0
            expenses = float(group[amount_col].sum())

        trends.append({
            "month": str(month),
            "income": round(income, 2),
            "expenses": round(expenses, 2),
            "net": round(income - expenses, 2),
            "count": len(group),
        })

    return sorted(trends, key=lambda x: x["month"])


def _extract_top_parties(
    df: pd.DataFrame,
    party_col: str,
    amount_col: str,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Top N parties by total transaction amount."""
    party_df = df.dropna(subset=[party_col])
    if len(party_df) == 0:
        return []

    grouped = party_df.groupby(party_col).agg(
        total=(amount_col, "sum"),
        count=(amount_col, "count"),
    ).sort_values("total", ascending=False).head(top_n)

    return [
        {
            "name": name,
            "total": round(float(row["total"]), 2),
            "count": int(row["count"]),
        }
        for name, row in grouped.iterrows()
    ]


def _extract_categories(
    df: pd.DataFrame,
    category_col: str,
    amount_col: str,
) -> list[dict[str, Any]]:
    """Breakdown by category (if assigned)."""
    cat_df = df.dropna(subset=[category_col])
    if len(cat_df) == 0:
        return []

    grouped = cat_df.groupby(category_col).agg(
        total=(amount_col, "sum"),
        count=(amount_col, "count"),
    ).sort_values("total", ascending=False)

    return [
        {
            "category": cat,
            "total": round(float(row["total"]), 2),
            "count": int(row["count"]),
        }
        for cat, row in grouped.iterrows()
    ]


# ── CLI demo ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    sample = pd.DataFrame({
        "txn_date": pd.to_datetime([
            "2026-01-05", "2026-01-10", "2026-01-20",
            "2026-02-05", "2026-02-15",
        ]),
        "description": ["Rent", "Sale", "Utilities", "Sale", "Internet"],
        "party_name": ["Landlord", "ABC Co", "WAPDA", "ABC Co", "PTCL"],
        "amount": [50000, 80000, 3500, 65000, 5000],
        "direction": ["debit", "credit", "debit", "credit", "debit"],
    })

    metadata = extract_metadata(sample)
    print(json.dumps(metadata, indent=2))
