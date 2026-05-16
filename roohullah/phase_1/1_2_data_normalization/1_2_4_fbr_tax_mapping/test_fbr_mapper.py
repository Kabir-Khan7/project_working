"""
Tests for 1.2.4 FBR Tax Mapping
---------------------------------
Run: python -m pytest test_fbr_mapper.py -v
"""

from datetime import date

import pytest
from fbr_mapper import FBRMapper, WHT_SECTIONS


@pytest.fixture
def mapper():
    return FBRMapper()


# ── Section 153: Services ────────────────────────────────────────────────────

class TestServicesMapping:
    def test_consulting(self, mapper):
        r = mapper.classify("Consulting")
        assert r.fbr_section == "153"
        assert r.wht_rate_filer == 0.08
        assert r.tax_applicable is True

    def test_legal_services(self, mapper):
        r = mapper.classify("Legal")
        assert r.fbr_section == "153"
        assert r.wht_rate_filer == 0.08

    def test_it_services(self, mapper):
        r = mapper.classify("IT Services")
        assert r.fbr_section == "153"

    def test_transport(self, mapper):
        r = mapper.classify("Transport")
        assert r.fbr_section == "153"
        assert r.annex_c_category == "Services rendered/provided"


# ── Section 153: Goods ───────────────────────────────────────────────────────

class TestGoodsMapping:
    def test_fuel(self, mapper):
        r = mapper.classify("Fuel")
        assert r.fbr_section == "153"
        assert r.wht_rate_filer == 0.04
        assert r.wht_rate_non_filer == 0.08

    def test_stationery(self, mapper):
        r = mapper.classify("Stationery")
        assert r.fbr_section == "153"
        assert r.annex_c_category == "Supply of goods"

    def test_raw_materials(self, mapper):
        r = mapper.classify("Raw Materials")
        assert r.fbr_section == "153"


# ── Section 153: Contracts ───────────────────────────────────────────────────

class TestContractsMapping:
    def test_construction(self, mapper):
        r = mapper.classify("Construction")
        assert r.fbr_section == "153"
        assert r.wht_rate_filer == 0.07
        assert r.annex_c_category == "Execution of contract"

    def test_renovation(self, mapper):
        r = mapper.classify("Renovation")
        assert r.fbr_section == "153"


# ── Section 155: Rent ────────────────────────────────────────────────────────

class TestRentMapping:
    def test_rent(self, mapper):
        r = mapper.classify("Rent")
        assert r.fbr_section == "155"
        assert r.wht_rate_filer == 0.10
        assert r.wht_rate_non_filer == 0.20

    def test_office_rent(self, mapper):
        r = mapper.classify("Office Rent")
        assert r.fbr_section == "155"
        assert r.annex_c_category == "Property rent"


# ── Section 149: Salary ──────────────────────────────────────────────────────

class TestSalaryMapping:
    def test_salary(self, mapper):
        r = mapper.classify("Salary")
        assert r.fbr_section == "149"
        assert r.tax_applicable is True

    def test_wages(self, mapper):
        r = mapper.classify("Wages")
        assert r.fbr_section == "149"


# ── Section 150/151: Financial ───────────────────────────────────────────────

class TestFinancialMapping:
    def test_dividend(self, mapper):
        r = mapper.classify("Dividend")
        assert r.fbr_section == "150"
        assert r.wht_rate_filer == 0.15
        assert r.wht_rate_non_filer == 0.30

    def test_bank_interest(self, mapper):
        r = mapper.classify("Bank Interest")
        assert r.fbr_section == "151"
        assert r.wht_rate_filer == 0.15


# ── Non-taxable categories ───────────────────────────────────────────────────

class TestNonTaxable:
    def test_utilities_not_taxable(self, mapper):
        r = mapper.classify("Utilities")
        assert r.tax_applicable is False
        assert r.fbr_section is None

    def test_electricity_not_taxable(self, mapper):
        r = mapper.classify("Electricity")
        assert r.tax_applicable is False

    def test_internet_not_taxable(self, mapper):
        r = mapper.classify("Internet")
        assert r.tax_applicable is False


# ── Unknown categories ───────────────────────────────────────────────────────

class TestUnknown:
    def test_random_category(self, mapper):
        r = mapper.classify("Random Unknown Thing")
        assert r.tax_applicable is False
        assert r.fbr_section is None
        assert r.fbr_category == "Not classified"


# ── Fuzzy matching ───────────────────────────────────────────────────────────

class TestFuzzyMatch:
    def test_fuel_and_transport(self, mapper):
        r = mapper.classify("Fuel & Transport")
        assert r.fbr_section == "153"
        assert r.tax_applicable is True

    def test_office_supplies_partial(self, mapper):
        r = mapper.classify("Office Supplies")
        assert r.fbr_section == "153"

    def test_staff_salary(self, mapper):
        r = mapper.classify("Staff Salary")
        assert r.fbr_section == "149"


# ── WHT Computation ──────────────────────────────────────────────────────────

class TestWHTComputation:
    def test_rent_filer(self, mapper):
        wht = mapper.compute_wht(100000, "Rent", is_filer=True)
        assert wht == 10000.0  # 10%

    def test_rent_non_filer(self, mapper):
        wht = mapper.compute_wht(100000, "Rent", is_filer=False)
        assert wht == 20000.0  # 20%

    def test_services_filer(self, mapper):
        wht = mapper.compute_wht(50000, "Consulting", is_filer=True)
        assert wht == 4000.0  # 8%

    def test_goods_filer(self, mapper):
        wht = mapper.compute_wht(50000, "Fuel", is_filer=True)
        assert wht == 2000.0  # 4%

    def test_non_taxable_zero(self, mapper):
        wht = mapper.compute_wht(100000, "Electricity", is_filer=True)
        assert wht == 0.0

    def test_unknown_zero(self, mapper):
        wht = mapper.compute_wht(100000, "Unknown Category")
        assert wht == 0.0


# ── Fiscal Year ──────────────────────────────────────────────────────────────

class TestFiscalYear:
    def test_august_new_fy(self, mapper):
        assert mapper.fiscal_year(date(2024, 8, 15)) == "2024-2025"

    def test_july_start_new_fy(self, mapper):
        assert mapper.fiscal_year(date(2024, 7, 1)) == "2024-2025"

    def test_march_previous_fy(self, mapper):
        assert mapper.fiscal_year(date(2025, 3, 10)) == "2024-2025"

    def test_june_end_previous_fy(self, mapper):
        assert mapper.fiscal_year(date(2024, 6, 30)) == "2023-2024"

    def test_january_previous_fy(self, mapper):
        assert mapper.fiscal_year(date(2025, 1, 1)) == "2024-2025"

    def test_december_current_fy(self, mapper):
        assert mapper.fiscal_year(date(2024, 12, 31)) == "2024-2025"


# ── Year-Month ───────────────────────────────────────────────────────────────

class TestYearMonth:
    def test_single_digit_month(self, mapper):
        assert mapper.year_month(date(2024, 1, 15)) == "2024-01"

    def test_double_digit_month(self, mapper):
        assert mapper.year_month(date(2024, 12, 1)) == "2024-12"
