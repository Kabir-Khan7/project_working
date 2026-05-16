"""
1.2.4 — FBR Tax Mapping (Standalone Module)
---------------------------------------------
Maps transaction categories to FBR (Federal Board of Revenue) tax heads.

Pakistan's tax compliance requires tracking:
    - Withholding Tax (WHT) rates per section
    - Annex-C category mappings for monthly returns
    - FBR section references (149, 150, 151, 153, 155, etc.)

This module provides:
    1. Category → FBR section mapping
    2. WHT rate lookup by section and filer status
    3. Transaction type classification for Annex-C
    4. Fiscal year calculation (Pakistani: July-June)

Dependencies:
    None (pure Python)

Usage:
    from fbr_mapper import FBRMapper

    mapper = FBRMapper()

    # Map a category to FBR head
    result = mapper.classify("Fuel & Transport")
    # result = FBRClassification(
    #     fbr_section="153",
    #     fbr_category="Goods/Services",
    #     wht_rate_filer=0.04,
    #     wht_rate_non_filer=0.08,
    #     annex_c_category="Services",
    #     tax_applicable=True,
    # )

    # Compute Pakistani fiscal year
    fy = mapper.fiscal_year(date(2024, 8, 15))
    # "2024-2025"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


# ── FBR WHT Sections ─────────────────────────────────────────────────────────

@dataclass
class WHTSection:
    """Withholding Tax section details."""
    section: str
    description: str
    rate_filer: float        # % for Active Taxpayers List (ATL) filers
    rate_non_filer: float    # % for non-filers (always higher)
    nature: str              # salary, services, goods, rent, dividend, etc.


# FBR WHT rate table (2024-2025 rates)
WHT_SECTIONS: dict[str, WHTSection] = {
    "149": WHTSection("149", "Salary", 0.0, 0.0, "salary"),
    "150": WHTSection("150", "Dividends", 0.15, 0.30, "dividend"),
    "151": WHTSection("151", "Profit on Debt (Bank Interest)", 0.15, 0.30, "interest"),
    "153_services": WHTSection("153", "Services", 0.08, 0.16, "services"),
    "153_goods": WHTSection("153", "Supply of Goods", 0.04, 0.08, "goods"),
    "153_contracts": WHTSection("153", "Contracts/Execution", 0.07, 0.14, "contracts"),
    "155": WHTSection("155", "Rent of Property", 0.10, 0.20, "rent"),
    "156": WHTSection("156", "Prize/Winnings", 0.20, 0.20, "prize"),
    "231A": WHTSection("231A", "Cash Withdrawal > 50K", 0.006, 0.012, "cash"),
    "236G": WHTSection("236G", "Sales (Retail)", 0.0, 0.02, "retail"),
}


# ── Category → FBR Section Mapping ──────────────────────────────────────────

CATEGORY_TO_FBR: dict[str, str] = {
    # Services (Section 153 - Services)
    "consulting": "153_services",
    "legal": "153_services",
    "accounting": "153_services",
    "audit": "153_services",
    "advertising": "153_services",
    "marketing": "153_services",
    "it services": "153_services",
    "software": "153_services",
    "maintenance": "153_services",
    "repair": "153_services",
    "cleaning": "153_services",
    "security": "153_services",
    "transport": "153_services",
    "courier": "153_services",
    "freight": "153_services",
    "commission": "153_services",
    "brokerage": "153_services",
    "professional fees": "153_services",

    # Goods (Section 153 - Goods)
    "supplies": "153_goods",
    "stationery": "153_goods",
    "fuel": "153_goods",
    "petrol": "153_goods",
    "diesel": "153_goods",
    "raw materials": "153_goods",
    "inventory": "153_goods",
    "stock": "153_goods",
    "purchases": "153_goods",
    "goods": "153_goods",
    "office supplies": "153_goods",
    "electrical": "153_goods",
    "hardware": "153_goods",
    "food": "153_goods",
    "beverages": "153_goods",

    # Contracts (Section 153 - Contracts)
    "construction": "153_contracts",
    "renovation": "153_contracts",
    "contract": "153_contracts",
    "project": "153_contracts",
    "civil work": "153_contracts",

    # Rent (Section 155)
    "rent": "155",
    "office rent": "155",
    "shop rent": "155",
    "warehouse rent": "155",
    "property rent": "155",
    "godown": "155",

    # Salary (Section 149)
    "salary": "149",
    "wages": "149",
    "bonus": "149",
    "overtime": "149",
    "payroll": "149",
    "staff salary": "149",

    # Dividends (Section 150)
    "dividend": "150",
    "profit distribution": "150",

    # Interest (Section 151)
    "bank interest": "151",
    "profit on savings": "151",
    "markup": "151",
    "interest income": "151",
    "interest expense": "151",

    # Utilities (typically NO WHT)
    "utilities": None,
    "electricity": None,
    "water": None,
    "gas": None,
    "internet": None,
    "telephone": None,
    "mobile": None,

    # Insurance (typically NO WHT)
    "insurance": None,
    "health insurance": None,
    "vehicle insurance": None,
}


# ── Annex-C Categories ───────────────────────────────────────────────────────

ANNEX_C_CATEGORIES = {
    "153_services": "Services rendered/provided",
    "153_goods": "Supply of goods",
    "153_contracts": "Execution of contract",
    "155": "Property rent",
    "149": "Salary/Wages",
    "150": "Dividend income",
    "151": "Profit on debt",
}


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class FBRClassification:
    """Result of FBR tax classification."""
    category: str
    fbr_section: Optional[str]
    fbr_category: str
    wht_rate_filer: float
    wht_rate_non_filer: float
    annex_c_category: str
    tax_applicable: bool


# ── FBR Mapper Class ─────────────────────────────────────────────────────────

class FBRMapper:
    """
    Maps transaction categories to FBR tax compliance data.

    Usage:
        mapper = FBRMapper()
        result = mapper.classify("Fuel & Transport")
        print(result.fbr_section)    # "153"
        print(result.wht_rate_filer) # 0.04
    """

    def classify(self, category: str) -> FBRClassification:
        """
        Classify a transaction category into FBR tax head.

        Args:
            category: Transaction category (e.g., "Fuel", "Rent", "Salary")

        Returns:
            FBRClassification with section, rates, and Annex-C info
        """
        cat_lower = category.lower().strip()

        # Direct match
        section_key = CATEGORY_TO_FBR.get(cat_lower)

        # Try partial match if direct fails
        if section_key is None:
            section_key = self._fuzzy_category_match(cat_lower)

        # No match → not tax-applicable
        if section_key is None:
            return FBRClassification(
                category=category,
                fbr_section=None,
                fbr_category="Not classified",
                wht_rate_filer=0.0,
                wht_rate_non_filer=0.0,
                annex_c_category="N/A",
                tax_applicable=False,
            )

        # Look up WHT section
        section = WHT_SECTIONS.get(section_key)
        if section is None:
            return FBRClassification(
                category=category,
                fbr_section=None,
                fbr_category="Not classified",
                wht_rate_filer=0.0,
                wht_rate_non_filer=0.0,
                annex_c_category="N/A",
                tax_applicable=False,
            )

        return FBRClassification(
            category=category,
            fbr_section=section.section,
            fbr_category=section.description,
            wht_rate_filer=section.rate_filer,
            wht_rate_non_filer=section.rate_non_filer,
            annex_c_category=ANNEX_C_CATEGORIES.get(section_key, "Other"),
            tax_applicable=True,
        )

    def compute_wht(
        self,
        amount: float,
        category: str,
        is_filer: bool = True,
    ) -> float:
        """
        Compute Withholding Tax amount for a transaction.

        Args:
            amount:    Transaction amount in PKR
            category:  Transaction category
            is_filer:  True if vendor is on ATL (Active Taxpayers List)

        Returns:
            WHT amount to deduct
        """
        result = self.classify(category)
        if not result.tax_applicable:
            return 0.0

        rate = result.wht_rate_filer if is_filer else result.wht_rate_non_filer
        return round(amount * rate, 2)

    @staticmethod
    def fiscal_year(dt: date) -> str:
        """
        Compute Pakistani fiscal year (July 1 → June 30).

        Examples:
            date(2024, 8, 15) → "2024-2025"  (Aug is in FY 2024-25)
            date(2025, 3, 10) → "2024-2025"  (Mar is still FY 2024-25)
            date(2024, 6, 30) → "2023-2024"  (June is end of FY 2023-24)
        """
        if dt.month >= 7:  # July onwards = start of new fiscal year
            return f"{dt.year}-{dt.year + 1}"
        else:  # Jan-June = end of previous fiscal year
            return f"{dt.year - 1}-{dt.year}"

    @staticmethod
    def year_month(dt: date) -> str:
        """Format date as year-month string for partitioning."""
        return f"{dt.year}-{dt.month:02d}"

    def _fuzzy_category_match(self, cat_lower: str) -> Optional[str]:
        """Try substring matching against known categories."""
        for known_cat, section_key in CATEGORY_TO_FBR.items():
            if section_key is None:
                continue
            if known_cat in cat_lower or cat_lower in known_cat:
                return section_key
        return None


# ── CLI Demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mapper = FBRMapper()

    categories = [
        "Fuel & Transport", "Rent", "Salary", "Consulting",
        "Office Supplies", "Electricity", "Construction",
        "Bank Interest", "Dividend",
    ]

    print("FBR Tax Classification:")
    print("-" * 80)
    print(f"{'Category':<20} {'Section':<10} {'Filer %':<10} {'Non-Filer %':<12} {'Annex-C'}")
    print("-" * 80)

    for cat in categories:
        r = mapper.classify(cat)
        section = r.fbr_section or "N/A"
        print(
            f"{cat:<20} {section:<10} "
            f"{r.wht_rate_filer*100:.1f}%{'':<6} "
            f"{r.wht_rate_non_filer*100:.1f}%{'':<8} "
            f"{r.annex_c_category}"
        )

    print(f"\nFiscal Year Examples:")
    print(f"  Aug 2024 → {mapper.fiscal_year(date(2024, 8, 15))}")
    print(f"  Mar 2025 → {mapper.fiscal_year(date(2025, 3, 10))}")
    print(f"  Jun 2024 → {mapper.fiscal_year(date(2024, 6, 30))}")

    print(f"\nWHT Calculation:")
    print(f"  Rent PKR 100,000 (filer): WHT = PKR {mapper.compute_wht(100000, 'Rent', True):,.0f}")
    print(f"  Rent PKR 100,000 (non-filer): WHT = PKR {mapper.compute_wht(100000, 'Rent', False):,.0f}")
