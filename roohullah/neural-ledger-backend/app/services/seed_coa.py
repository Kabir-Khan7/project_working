"""
services/seed_coa.py
--------------------
Seed a basic Pakistani-SME Chart of Accounts for a freshly created org.
Codes follow a 4-digit hierarchical scheme (1xxx assets, 2xxx liabilities, ...).
"""

from typing import List, Tuple

# (code, name, type, parent_code)
DEFAULT_COA: List[Tuple[str, str, str, str | None]] = [
    # ── 1xxx Assets ───────────────────────────────────────────────────────────
    ("1000", "Assets",                      "asset",     None),
    ("1010", "Cash in Hand",                "asset",     "1000"),
    ("1020", "Bank — Current Account",      "asset",     "1000"),
    ("1030", "Bank — Savings Account",      "asset",     "1000"),
    ("1100", "Accounts Receivable",         "asset",     "1000"),
    ("1200", "Inventory",                   "asset",     "1000"),
    ("1300", "Advances to Suppliers",       "asset",     "1000"),
    ("1500", "Fixed Assets",                "asset",     "1000"),

    # ── 2xxx Liabilities ──────────────────────────────────────────────────────
    ("2000", "Liabilities",                 "liability", None),
    ("2010", "Accounts Payable",            "liability", "2000"),
    ("2020", "Sales Tax Payable",           "liability", "2000"),
    ("2030", "Income Tax Payable",          "liability", "2000"),
    ("2040", "Salaries Payable",            "liability", "2000"),
    ("2100", "Bank Loans",                  "liability", "2000"),

    # ── 3xxx Equity ───────────────────────────────────────────────────────────
    ("3000", "Equity",                      "equity",    None),
    ("3010", "Owner's Capital",             "equity",    "3000"),
    ("3020", "Retained Earnings",           "equity",    "3000"),

    # ── 4xxx Revenue ──────────────────────────────────────────────────────────
    ("4000", "Revenue",                     "revenue",   None),
    ("4010", "Sales — Local",               "revenue",   "4000"),
    ("4020", "Sales — Export",              "revenue",   "4000"),
    ("4030", "Service Income",              "revenue",   "4000"),
    ("4900", "Other Income",                "revenue",   "4000"),

    # ── 5xxx Expenses ─────────────────────────────────────────────────────────
    ("5000", "Expenses",                    "expense",   None),
    ("5010", "Cost of Goods Sold",          "expense",   "5000"),
    ("5100", "Salaries & Wages",            "expense",   "5000"),
    ("5110", "Rent",                        "expense",   "5000"),
    ("5120", "Utilities",                   "expense",   "5000"),
    ("5130", "Internet & Telecom",          "expense",   "5000"),
    ("5140", "Office Supplies",             "expense",   "5000"),
    ("5150", "Travel & Conveyance",         "expense",   "5000"),
    ("5160", "Marketing & Advertising",     "expense",   "5000"),
    ("5170", "Professional Fees",           "expense",   "5000"),
    ("5180", "Bank Charges",                "expense",   "5000"),
    ("5190", "Repairs & Maintenance",       "expense",   "5000"),
    ("5200", "Depreciation",                "expense",   "5000"),
    ("5900", "Miscellaneous Expense",       "expense",   "5000"),
]


async def seed_chart_of_accounts(db, org_id: str) -> int:
    """
    Inserts the default COA for the given org. Returns count inserted.
    Idempotent: skips codes that already exist.
    """
    from sqlalchemy import select
    from app.models.account import Account

    existing = await db.execute(
        select(Account.code).where(Account.org_id == org_id)
    )
    existing_codes = {row[0] for row in existing.all()}

    inserted = 0
    for code, name, acc_type, parent in DEFAULT_COA:
        if code in existing_codes:
            continue
        db.add(Account(
            org_id=org_id, code=code, name=name,
            type=acc_type, parent_code=parent,
        ))
        inserted += 1

    await db.commit()
    return inserted
