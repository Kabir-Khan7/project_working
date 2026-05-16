"""
Tests for 1.2.3 Security Gates
--------------------------------
Run: python -m pytest test_security_gates.py -v
"""

import pytest
from security_gates import (
    SecurityGatekeeper, GateResult, parse_amount,
    RESERVED_COLUMN_NAMES,
)


@pytest.fixture
def gatekeeper():
    return SecurityGatekeeper()


@pytest.fixture
def sample_headers():
    return ["Date", "Amount", "Description", "Vendor"]


@pytest.fixture
def sample_rows():
    return [
        {"Date": "15/01/2024", "Amount": "5000", "Description": "Rent", "Vendor": "Landlord"},
        {"Date": "16/01/2024", "Amount": "3000", "Description": "Utilities", "Vendor": "WAPDA"},
    ]


# ── Gate 1: File Size ────────────────────────────────────────────────────────

class TestGate1FileSize:
    def test_normal_file_passes(self, gatekeeper, sample_rows, sample_headers):
        result = gatekeeper.run_all_gates(sample_rows, sample_headers, file_size_bytes=1024)
        assert result.passed is True
        assert result.blocked is False

    def test_huge_file_blocked(self, gatekeeper, sample_rows, sample_headers):
        result = gatekeeper.run_all_gates(
            sample_rows, sample_headers,
            file_size_bytes=200 * 1024 * 1024,  # 200 MB
        )
        assert result.passed is False
        assert result.blocked is True
        assert "Gate 1" in result.block_reason

    def test_exact_limit_passes(self, gatekeeper, sample_rows, sample_headers):
        result = gatekeeper.run_all_gates(
            sample_rows, sample_headers,
            file_size_bytes=100 * 1024 * 1024,  # exactly 100 MB
        )
        assert result.passed is True


# ── Gate 2: Row Count ────────────────────────────────────────────────────────

class TestGate2RowCount:
    def test_normal_row_count(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024-01-01"}] * 100
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=1024)
        assert result.passed is True

    def test_excessive_rows_blocked(self, sample_headers):
        gatekeeper = SecurityGatekeeper(max_row_count=10)
        rows = [{"Date": "2024-01-01"}] * 15
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=1024)
        assert result.passed is False
        assert result.blocked is True
        assert "Gate 2" in result.block_reason


# ── Gate 3: Formula Neutralization ───────────────────────────────────────────

class TestGate3Formula:
    def test_hyperlink_formula_blocked(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024-01-01", "Amount": "5000",
                 "Description": '=HYPERLINK("http://evil.com","Click")',
                 "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert "FORMULA_REMOVED:" in result.sanitized_rows[0]["Description"]
        assert any("Gate 3" in w for w in result.warnings)

    def test_equals_formula_blocked(self, gatekeeper, sample_headers):
        rows = [{"Date": "=1+1", "Amount": "5000",
                 "Description": "Normal", "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert result.sanitized_rows[0]["Date"].startswith("FORMULA_REMOVED:")

    def test_cmd_formula_blocked(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024", "Amount": "5000",
                 "Description": "=CMD('calc')", "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert "FORMULA_REMOVED:" in result.sanitized_rows[0]["Description"]

    def test_negative_number_allowed(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024-01-01", "Amount": "-5000",
                 "Description": "Refund", "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert result.sanitized_rows[0]["Amount"] == "-5000"

    def test_positive_number_allowed(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024-01-01", "Amount": "+5000",
                 "Description": "Credit", "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert result.sanitized_rows[0]["Amount"] == "+5000"

    def test_at_sign_blocked(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024", "Amount": "5000",
                 "Description": "@SUM(A1:A10)", "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert "FORMULA_REMOVED:" in result.sanitized_rows[0]["Description"]

    def test_pipe_injection_blocked(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024", "Amount": "5000",
                 "Description": "|calc|", "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert "FORMULA_REMOVED:" in result.sanitized_rows[0]["Description"]

    def test_normal_text_untouched(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024-01-01", "Amount": "5000",
                 "Description": "Payment to Ali Khan", "Vendor": "Ali Khan"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert result.sanitized_rows[0]["Description"] == "Payment to Ali Khan"


# ── Gate 4: Reserved Names ───────────────────────────────────────────────────

class TestGate4ReservedNames:
    def test_reserved_column_renamed(self, gatekeeper, sample_rows):
        headers = ["Date", "Amount", "quality_score", "Description"]
        result = gatekeeper.run_all_gates(sample_rows, headers, file_size_bytes=100)
        assert "raw_quality_score" in result.sanitized_headers
        assert "quality_score" not in result.sanitized_headers
        assert any("Gate 4" in w for w in result.warnings)

    def test_embedding_text_renamed(self, gatekeeper, sample_rows):
        headers = ["Date", "embedding_text"]
        result = gatekeeper.run_all_gates(sample_rows, headers, file_size_bytes=100)
        assert "raw_embedding_text" in result.sanitized_headers

    def test_normal_columns_untouched(self, gatekeeper, sample_rows, sample_headers):
        result = gatekeeper.run_all_gates(sample_rows, sample_headers, file_size_bytes=100)
        assert result.sanitized_headers == sample_headers

    def test_renamed_columns_tracked(self, gatekeeper, sample_rows):
        headers = ["Date", "bronze_id", "Amount"]
        result = gatekeeper.run_all_gates(sample_rows, headers, file_size_bytes=100)
        assert result.renamed_columns == {"bronze_id": "raw_bronze_id"}


# ── Gate 5: Unicode Normalization ────────────────────────────────────────────

class TestGate5Unicode:
    def test_nfc_normalization(self, gatekeeper, sample_rows):
        # NFD form of "é" (e + combining accent) vs NFC (single char)
        headers = ["Date", "Café"]  # NFD "Café"
        result = gatekeeper.run_all_gates(sample_rows, headers, file_size_bytes=100)
        assert result.sanitized_headers[1] == "Café"  # NFC

    def test_normal_ascii_untouched(self, gatekeeper, sample_rows, sample_headers):
        result = gatekeeper.run_all_gates(sample_rows, sample_headers, file_size_bytes=100)
        assert result.sanitized_headers == sample_headers

    def test_urdu_preserved(self, gatekeeper, sample_rows):
        headers = ["تاریخ", "رقم"]  # تاریخ, رقم
        result = gatekeeper.run_all_gates(sample_rows, headers, file_size_bytes=100)
        assert "تاریخ" in result.sanitized_headers


# ── Gate 6: LLM Output Validation ────────────────────────────────────────────

class TestGate6LLMValidation:
    def test_valid_mapping_accepted(self):
        valid_targets = {"transaction_date", "amount", "description", "vendor"}
        llm_response = {"Taareekh": "transaction_date", "Raqam": "amount"}
        validated, warnings = SecurityGatekeeper.validate_llm_mapping(
            llm_response, valid_targets
        )
        assert validated == {"Taareekh": "transaction_date", "Raqam": "amount"}
        assert len(warnings) == 0

    def test_invalid_target_rejected(self):
        valid_targets = {"transaction_date", "amount"}
        llm_response = {"Col1": "nonexistent_field"}
        validated, warnings = SecurityGatekeeper.validate_llm_mapping(
            llm_response, valid_targets
        )
        assert "Col1" not in validated
        assert any("Gate 6" in w for w in warnings)

    def test_reserved_field_rejected(self):
        valid_targets = {"quality_score", "amount"}
        llm_response = {"Score": "quality_score"}
        validated, warnings = SecurityGatekeeper.validate_llm_mapping(
            llm_response, valid_targets
        )
        assert "Score" not in validated
        assert any("reserved" in w.lower() for w in warnings)

    def test_long_target_rejected(self):
        valid_targets = {"a" * 100}  # a super long valid field (hypothetical)
        llm_response = {"Col": "a" * 100}
        validated, warnings = SecurityGatekeeper.validate_llm_mapping(
            llm_response, valid_targets
        )
        assert "Col" not in validated
        assert any("too long" in w for w in warnings)


# ── Gate 7: Cell Length Truncation ───────────────────────────────────────────

class TestGate7CellLength:
    def test_normal_length_untouched(self, gatekeeper, sample_rows, sample_headers):
        result = gatekeeper.run_all_gates(sample_rows, sample_headers, file_size_bytes=100)
        assert result.sanitized_rows[0]["Description"] == "Rent"

    def test_long_cell_truncated(self, gatekeeper, sample_headers):
        rows = [{"Date": "2024", "Amount": "5000",
                 "Description": "x" * 20000, "Vendor": "Safe"}]
        result = gatekeeper.run_all_gates(rows, sample_headers, file_size_bytes=100)
        assert len(result.sanitized_rows[0]["Description"]) == 10000
        assert any("Gate 7" in w for w in result.warnings)


# ── Amount Parser ────────────────────────────────────────────────────────────

class TestAmountParser:
    def test_plain_integer(self):
        assert parse_amount("5000") == 5000.0

    def test_with_commas(self):
        assert parse_amount("45,000") == 45000.0

    def test_pkr_prefix(self):
        assert parse_amount("PKR 45,000") == 45000.0

    def test_rs_prefix(self):
        assert parse_amount("Rs. 12,500.50") == 12500.5

    def test_parentheses_negative(self):
        assert parse_amount("(5,000)") == -5000.0

    def test_usd_prefix(self):
        assert parse_amount("$1,200.00") == 1200.0

    def test_na_returns_none(self):
        assert parse_amount("N/A") is None

    def test_nil_returns_none(self):
        assert parse_amount("nil") is None

    def test_empty_string(self):
        assert parse_amount("") is None

    def test_none_input(self):
        assert parse_amount(None) is None

    def test_int_input(self):
        assert parse_amount(5000) == 5000.0

    def test_float_input(self):
        assert parse_amount(12500.5) == 12500.5

    def test_dash_returns_none(self):
        assert parse_amount("-") is None

    def test_negative_number(self):
        assert parse_amount("-5000") == -5000.0

    def test_with_dr_suffix(self):
        assert parse_amount("5000 DR") == 5000.0

    def test_with_cr_suffix(self):
        assert parse_amount("12000 Cr") == 12000.0


# ── Integration ──────────────────────────────────────────────────────────────

class TestIntegration:
    def test_all_gates_pass_clean_data(self, gatekeeper, sample_rows, sample_headers):
        result = gatekeeper.run_all_gates(sample_rows, sample_headers, file_size_bytes=1024)
        assert result.passed is True
        assert result.blocked is False
        assert len(result.warnings) == 0
        assert len(result.sanitized_rows) == 2

    def test_mixed_issues_handled(self, gatekeeper):
        headers = ["Date", "quality_score", "Amount"]
        rows = [
            {"Date": "2024-01-01", "quality_score": "0.9",
             "Amount": '=CMD("calc")'},
        ]
        result = gatekeeper.run_all_gates(rows, headers, file_size_bytes=500)
        assert result.passed is True  # not blocked, just sanitized
        assert "raw_quality_score" in result.sanitized_headers
        assert "FORMULA_REMOVED:" in result.sanitized_rows[0]["Amount"]
        assert len(result.warnings) >= 2  # at least Gate 3 + Gate 4
