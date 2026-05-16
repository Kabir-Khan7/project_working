"""
Tests for 1.1.4 Accounting Software Detector
----------------------------------------------
Run: python -m pytest test_software_detector.py -v
"""

import pytest
from software_detector import detect_file, is_supported, is_ignored, DetectionResult


# ── Software Detection ───────────────────────────────────────────────────────

class TestTallyDetection:
    def test_tallyprime_daybook(self):
        result = detect_file("TallyPrime_Daybook_Jan2024.xlsx")
        assert result.source_software == "tally"
        assert result.confidence >= 0.90

    def test_tally_export(self):
        result = detect_file("Tally_Export_2024.csv")
        assert result.source_software == "tally"
        assert result.confidence >= 0.85

    def test_tally_case_insensitive(self):
        result = detect_file("TALLYPRIME_REPORT.xlsx")
        assert result.source_software == "tally"

    def test_daybook_implies_tally(self):
        result = detect_file("daybook_january.xlsx")
        assert result.source_software == "tally"
        assert result.confidence >= 0.70


class TestQuickBooksDetection:
    def test_quickbooks_desktop(self):
        result = detect_file("QuickBooks_Desktop_GL.xlsx")
        assert result.source_software == "quickbooks_desktop"
        assert result.confidence >= 0.90

    def test_quickbooks_online(self):
        result = detect_file("QuickBooks_Online_Export.csv")
        assert result.source_software == "quickbooks_online"
        assert result.confidence >= 0.90

    def test_quickbooks_generic(self):
        result = detect_file("QuickBooks_General_Ledger.xlsx")
        assert result.source_software == "quickbooks_desktop"
        assert result.confidence >= 0.85

    def test_qb_export(self):
        result = detect_file("QB_Export_Jan.csv")
        assert result.source_software == "quickbooks_desktop"


class TestOtherSoftware:
    def test_ledgermax(self):
        result = detect_file("LedgerMax_Report_Jan.xlsx")
        assert result.source_software == "ledgermax"
        assert result.confidence >= 0.95

    def test_xero(self):
        result = detect_file("Xero_Export_Jan.csv")
        assert result.source_software == "xero"
        assert result.confidence >= 0.90

    def test_moneypex(self):
        result = detect_file("Moneypex_Transactions.xlsx")
        assert result.source_software == "moneypex"
        assert result.confidence >= 0.95

    def test_odoo(self):
        result = detect_file("Odoo_Journal_Entries.csv")
        assert result.source_software == "odoo"

    def test_sage50(self):
        result = detect_file("Sage_50_Export.xlsx")
        assert result.source_software == "sage50"


class TestBankPDFs:
    def test_hbl_statement(self):
        result = detect_file("HBL_Statement_Jan2024.pdf")
        assert result.source_software == "bank_pdf_hbl"
        assert result.confidence >= 0.90

    def test_ubl_statement(self):
        result = detect_file("UBL_Account_Statement.pdf")
        assert result.source_software == "bank_pdf_ubl"

    def test_alfalah(self):
        result = detect_file("Alfalah_eStatement.pdf")
        assert result.source_software == "bank_pdf_alfalah"

    def test_meezan(self):
        result = detect_file("Meezan_Statement.pdf")
        assert result.source_software == "bank_pdf_meezan"

    def test_nbp(self):
        result = detect_file("NBP_Statement_2024.pdf")
        assert result.source_software == "bank_pdf_nbp"

    def test_mcb(self):
        result = detect_file("MCB_Statement_Jan.pdf")
        assert result.source_software == "bank_pdf_mcb"

    def test_jazzcash(self):
        result = detect_file("JazzCash_Statement.pdf")
        assert result.source_software == "bank_pdf_jazzcash"

    def test_easypaisa(self):
        result = detect_file("Easypaisa_transactions.pdf")
        assert result.source_software == "bank_pdf_easypaisa"

    def test_generic_bank_statement(self):
        result = detect_file("Account_Statement_2024.pdf")
        assert result.source_software == "bank_pdf_generic"
        assert result.confidence >= 0.70


class TestFBRCompliance:
    def test_annex_c(self):
        result = detect_file("fbr_annex_c_jan.xlsx")
        assert result.source_software == "fbr_annex_c"

    def test_wht_register(self):
        result = detect_file("withholding_tax_jan.xlsx")
        assert result.source_software == "fbr_wht"

    def test_eobi(self):
        result = detect_file("eobi_register.xlsx")
        assert result.source_software == "eobi_register"


class TestGenericFiles:
    def test_unrecognized_excel(self):
        result = detect_file("sales_register_jan.xlsx")
        assert result.source_software == "manual_excel"
        assert result.confidence == 0.50

    def test_unrecognized_csv(self):
        result = detect_file("random_data.csv")
        assert result.source_software == "manual_csv"
        assert result.confidence == 0.50

    def test_unknown_pdf(self):
        result = detect_file("random_document.pdf")
        assert result.source_software == "unknown_pdf"
        assert result.confidence == 0.30


# ── Source Type Detection ────────────────────────────────────────────────────

class TestSourceType:
    def test_xlsx(self):
        assert detect_file("test.xlsx").source_type == "xlsx"

    def test_xls(self):
        assert detect_file("test.xls").source_type == "xlsx"

    def test_csv(self):
        assert detect_file("test.csv").source_type == "csv"

    def test_pdf(self):
        assert detect_file("test.pdf").source_type == "pdf"

    def test_json(self):
        assert detect_file("test.json").source_type == "json"

    def test_unsupported(self):
        result = detect_file("test.docx")
        assert result.source_type == "unknown"
        assert result.is_supported is False


# ── is_supported ─────────────────────────────────────────────────────────────

class TestIsSupported:
    def test_xlsx_supported(self):
        assert is_supported("file.xlsx") is True

    def test_csv_supported(self):
        assert is_supported("file.csv") is True

    def test_pdf_supported(self):
        assert is_supported("file.pdf") is True

    def test_docx_not_supported(self):
        assert is_supported("file.docx") is False

    def test_txt_not_supported(self):
        assert is_supported("file.txt") is False


# ── is_ignored ───────────────────────────────────────────────────────────────

class TestIsIgnored:
    def test_excel_lock_file(self):
        assert is_ignored("~$workbook.xlsx") is True

    def test_hidden_file(self):
        assert is_ignored(".hidden_config") is True

    def test_tmp_file(self):
        assert is_ignored("data.tmp") is True

    def test_bak_file(self):
        assert is_ignored("backup.bak") is True

    def test_swp_file(self):
        assert is_ignored("file.swp") is True

    def test_lock_file(self):
        assert is_ignored("process.lock") is True

    def test_normal_excel_not_ignored(self):
        assert is_ignored("sales_jan.xlsx") is False

    def test_normal_csv_not_ignored(self):
        assert is_ignored("data.csv") is False


# ── Full path handling ───────────────────────────────────────────────────────

class TestFullPaths:
    def test_full_windows_path(self):
        result = detect_file(r"C:\Users\data_vault\TallyPrime_Jan.xlsx")
        assert result.source_software == "tally"
        assert result.file_name == "TallyPrime_Jan.xlsx"

    def test_full_unix_path(self):
        result = detect_file("/home/user/data_vault/QuickBooks_GL.csv")
        assert result.source_software == "quickbooks_desktop"

    def test_ignored_with_full_path(self):
        assert is_ignored(r"C:\vault\~$temp.xlsx") is True
