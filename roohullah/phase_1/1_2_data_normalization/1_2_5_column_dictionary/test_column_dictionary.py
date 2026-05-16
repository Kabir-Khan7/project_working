"""
Tests for 1.2.5 Column Dictionary & Fuzzy Mapper
---------------------------------------------------
Run: python -m pytest test_column_dictionary.py -v
"""

import pytest
from column_dictionary import ColumnMapper, STANDARD_FIELDS


@pytest.fixture
def mapper():
    return ColumnMapper()


# ── Software-Specific Mapping (Layer 1) ──────────────────────────────────────

class TestTallyMappings:
    def test_particulars(self, mapper):
        r = mapper.lookup("Particulars", software="tally")
        assert r.mapped_to == "description"
        assert r.confidence == 0.95
        assert r.source == "software"

    def test_vch_type(self, mapper):
        r = mapper.lookup("Vch Type", software="tally")
        assert r.mapped_to == "voucher_type"

    def test_vch_no(self, mapper):
        r = mapper.lookup("Vch No.", software="tally")
        assert r.mapped_to == "voucher_number"

    def test_ledger_name(self, mapper):
        r = mapper.lookup("Ledger Name", software="tally")
        assert r.mapped_to == "account_name"


class TestQuickBooksMappings:
    def test_memo(self, mapper):
        r = mapper.lookup("Memo", software="quickbooks_desktop")
        assert r.mapped_to == "description"
        assert r.confidence == 0.95

    def test_num(self, mapper):
        r = mapper.lookup("Num", software="quickbooks_desktop")
        assert r.mapped_to == "reference"

    def test_class(self, mapper):
        r = mapper.lookup("Class", software="quickbooks_desktop")
        assert r.mapped_to == "category"


class TestBankMappings:
    def test_hbl_narration(self, mapper):
        r = mapper.lookup("Narration", software="bank_pdf_hbl")
        assert r.mapped_to == "description"

    def test_meezan_withdrawal(self, mapper):
        r = mapper.lookup("Withdrawal", software="bank_pdf_meezan")
        assert r.mapped_to == "amount_debit"

    def test_meezan_deposit(self, mapper):
        r = mapper.lookup("Deposit", software="bank_pdf_meezan")
        assert r.mapped_to == "amount_credit"


# ── Urdu Script Mapping (Layer 2) ────────────────────────────────────────────

class TestUrduMappings:
    def test_tareekh(self, mapper):
        r = mapper.lookup("تاریخ")
        assert r.mapped_to == "transaction_date"
        assert r.confidence == 0.90
        assert r.source == "urdu"

    def test_raqam(self, mapper):
        r = mapper.lookup("رقم")
        assert r.mapped_to == "net_amount"

    def test_tafseel(self, mapper):
        r = mapper.lookup("تفصیل")
        assert r.mapped_to == "description"

    def test_naam(self, mapper):
        r = mapper.lookup("نام")
        assert r.mapped_to == "vendor"

    def test_jama(self, mapper):
        r = mapper.lookup("جمع")
        assert r.mapped_to == "amount_credit"

    def test_nikaasi(self, mapper):
        r = mapper.lookup("نکاسی")
        assert r.mapped_to == "amount_debit"


# ── Roman Urdu Mapping (Layer 3) ─────────────────────────────────────────────

class TestRomanUrduMappings:
    def test_taareekh(self, mapper):
        r = mapper.lookup("Taareekh")
        assert r.mapped_to == "transaction_date"
        assert r.confidence == 0.85
        assert r.source == "roman_urdu"

    def test_raqam(self, mapper):
        r = mapper.lookup("Raqam")
        assert r.mapped_to == "net_amount"

    def test_tafseelat(self, mapper):
        r = mapper.lookup("Tafseelat")
        assert r.mapped_to == "description"

    def test_kharcha(self, mapper):
        r = mapper.lookup("Kharcha")
        assert r.mapped_to == "amount_debit"

    def test_baqaya(self, mapper):
        r = mapper.lookup("Baqaya")
        assert r.mapped_to == "balance"


# ── General Mapping (Layer 4) ────────────────────────────────────────────────

class TestGeneralMappings:
    def test_date(self, mapper):
        r = mapper.lookup("Date")
        assert r.mapped_to == "transaction_date"
        assert r.confidence == 0.80

    def test_amount(self, mapper):
        r = mapper.lookup("Amount")
        assert r.mapped_to == "net_amount"

    def test_dr(self, mapper):
        r = mapper.lookup("Dr")
        assert r.mapped_to == "amount_debit"

    def test_cr(self, mapper):
        r = mapper.lookup("Cr")
        assert r.mapped_to == "amount_credit"

    def test_narration(self, mapper):
        r = mapper.lookup("Narration")
        assert r.mapped_to == "description"

    def test_cheque_no(self, mapper):
        r = mapper.lookup("Cheque No")
        assert r.mapped_to == "reference"

    def test_voucher_no(self, mapper):
        r = mapper.lookup("Voucher No")
        assert r.mapped_to == "voucher_number"


# ── Normalized Matching (Layer 5) ────────────────────────────────────────────

class TestNormalizedMatching:
    def test_with_underscores(self, mapper):
        r = mapper.lookup("Transaction_Date")
        assert r.mapped_to == "transaction_date"

    def test_with_extra_spaces(self, mapper):
        r = mapper.lookup("  Date  ")
        assert r.mapped_to == "transaction_date"

    def test_different_case(self, mapper):
        r = mapper.lookup("AMOUNT")
        assert r.mapped_to == "net_amount"


# ── Fuzzy Matching (Layer 6) ─────────────────────────────────────────────────

class TestFuzzyMatching:
    def test_typo_in_date(self, mapper):
        r = mapper.lookup("Transacton Date")  # typo
        assert r.mapped_to is not None
        assert r.source == "fuzzy"
        assert r.confidence >= 0.4

    def test_close_to_description(self, mapper):
        r = mapper.lookup("Descrption")  # missing 'i'
        assert r.mapped_to == "description"
        assert r.source == "fuzzy"

    def test_completely_unknown(self, mapper):
        r = mapper.lookup("xyzzy_foobar_12345")
        # Should have very low or no match
        assert r.confidence < 0.5 or r.mapped_to is None


# ── map_all ──────────────────────────────────────────────────────────────────

class TestMapAll:
    def test_tally_columns(self, mapper):
        columns = ["Date", "Particulars", "Vch Type", "Debit", "Credit"]
        results = mapper.map_all(columns, software="tally")
        assert results["Particulars"].mapped_to == "description"
        assert results["Vch Type"].mapped_to == "voucher_type"
        assert all(r.mapped_to is not None for r in results.values())

    def test_mixed_columns(self, mapper):
        columns = ["تاریخ", "Amount", "Taareekh"]
        results = mapper.map_all(columns)
        assert results["تاریخ"].source == "urdu"
        assert results["Amount"].source == "general"
        assert results["Taareekh"].source == "roman_urdu"


# ── Coverage ─────────────────────────────────────────────────────────────────

class TestCoverage:
    def test_full_coverage_tally(self, mapper):
        columns = ["Date", "Particulars", "Debit", "Credit"]
        coverage = mapper.get_coverage(columns, software="tally")
        assert coverage == 1.0

    def test_partial_coverage(self, mapper):
        columns = ["Date", "Amount", "totally_unknown_xyz"]
        coverage = mapper.get_coverage(columns)
        assert 0.5 <= coverage <= 1.0

    def test_empty_columns(self, mapper):
        assert mapper.get_coverage([]) == 0.0
