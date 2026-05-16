"""Tests for silver_writer module."""

from __future__ import annotations

import json
import uuid
from datetime import date

import duckdb
import pytest

import sys
import os

# Ensure the module can be imported directly when running tests from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from silver_writer import (  # noqa: E402
    SilverWriter,
    ProcessResult,
    compute_fiscal_year,
    compute_quality_score,
    detect_language,
    mask_pii,
    parse_amount,
    parse_date,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Create an in-memory DuckDB connection with all required tables."""
    db = duckdb.connect(":memory:")

    db.execute("""
        CREATE TABLE IF NOT EXISTS bronze_transactions (
            bronze_id VARCHAR PRIMARY KEY,
            source_type VARCHAR NOT NULL,
            source_software VARCHAR NOT NULL,
            source_file VARCHAR NOT NULL,
            source_file_hash VARCHAR NOT NULL,
            source_row_number INTEGER,
            raw_content VARCHAR NOT NULL,
            raw_headers VARCHAR,
            ingestion_batch_id VARCHAR NOT NULL,
            processing_status VARCHAR NOT NULL DEFAULT 'pending',
            ingested_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS silver_transactions (
            silver_id VARCHAR PRIMARY KEY,
            bronze_id VARCHAR NOT NULL,
            transaction_date DATE,
            year_month VARCHAR(7),
            fiscal_year VARCHAR(9),
            description VARCHAR,
            description_masked VARCHAR,
            vendor VARCHAR,
            category VARCHAR,
            amount_debit DOUBLE DEFAULT 0.0,
            amount_credit DOUBLE DEFAULT 0.0,
            net_amount DOUBLE GENERATED ALWAYS AS (amount_credit - amount_debit) VIRTUAL,
            currency VARCHAR(3) DEFAULT 'PKR',
            language_detected VARCHAR(5) DEFAULT 'en',
            is_duplicate BOOLEAN DEFAULT FALSE,
            duplicate_of VARCHAR,
            pii_masked BOOLEAN DEFAULT FALSE,
            pii_types_found VARCHAR,
            quality_score DOUBLE DEFAULT 0.0,
            normalised_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS silver_quarantine (
            quarantine_id VARCHAR PRIMARY KEY,
            bronze_id VARCHAR NOT NULL,
            reason VARCHAR NOT NULL,
            raw_content VARCHAR,
            error_detail VARCHAR,
            quarantined_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_audit_log (
            log_id VARCHAR PRIMARY KEY,
            operation VARCHAR NOT NULL,
            source_layer VARCHAR NOT NULL,
            batch_id VARCHAR,
            status VARCHAR NOT NULL,
            rows_affected INTEGER DEFAULT 0,
            error_detail VARCHAR,
            duration_ms INTEGER,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    yield db
    db.close()


def _insert_bronze_row(conn, bronze_id: str, raw_content: dict, batch_id: str = "batch-001"):
    """Helper to insert a bronze row for testing."""
    conn.execute(
        """
        INSERT INTO bronze_transactions (
            bronze_id, source_type, source_software, source_file,
            source_file_hash, source_row_number, raw_content,
            ingestion_batch_id, processing_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        [
            bronze_id,
            "bank_statement",
            "excel",
            "test.xlsx",
            "abc123",
            1,
            json.dumps(raw_content),
            batch_id,
        ],
    )


# ---------------------------------------------------------------------------
# Tests: parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_dd_mm_yyyy(self):
        assert parse_date("15/03/2024") == date(2024, 3, 15)

    def test_yyyy_mm_dd(self):
        assert parse_date("2024-03-15") == date(2024, 3, 15)

    def test_mm_dd_yyyy(self):
        assert parse_date("03/15/2024") == date(2024, 3, 15)

    def test_dd_mmm_yyyy(self):
        assert parse_date("15-Jan-2024") == date(2024, 1, 15)

    def test_dd_mm_yyyy_dash(self):
        assert parse_date("15-03-2024") == date(2024, 3, 15)

    def test_invalid_date(self):
        assert parse_date("not-a-date") is None

    def test_empty_string(self):
        assert parse_date("") is None

    def test_none(self):
        assert parse_date(None) is None

    def test_whitespace(self):
        assert parse_date("  2024-03-15  ") == date(2024, 3, 15)


# ---------------------------------------------------------------------------
# Tests: parse_amount
# ---------------------------------------------------------------------------


class TestParseAmount:
    def test_plain_number(self):
        assert parse_amount("45000") == 45000.0

    def test_with_commas(self):
        assert parse_amount("45,000") == 45000.0

    def test_pkr_prefix(self):
        assert parse_amount("PKR 45,000") == 45000.0

    def test_rs_prefix(self):
        assert parse_amount("Rs. 1,200.50") == 1200.50

    def test_parentheses_negative(self):
        assert parse_amount("(5000)") == -5000.0

    def test_negative_sign(self):
        assert parse_amount("-3000") == -3000.0

    def test_empty_string(self):
        assert parse_amount("") is None

    def test_none(self):
        assert parse_amount(None) is None

    def test_numeric_input(self):
        assert parse_amount(1234.5) == 1234.5

    def test_pkr_with_commas_and_decimals(self):
        assert parse_amount("PKR 1,23,456.78") == 123456.78


# ---------------------------------------------------------------------------
# Tests: detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_english(self):
        assert detect_language("Payment for electricity bill") == "en"

    def test_urdu(self):
        assert detect_language("بجلی کا بل ادائیگی") == "ur"

    def test_mixed(self):
        assert detect_language("Payment بجلی bill") == "mixed"

    def test_empty(self):
        assert detect_language("") == "en"

    def test_none(self):
        assert detect_language(None) == "en"

    def test_numbers_only(self):
        assert detect_language("12345") == "en"


# ---------------------------------------------------------------------------
# Tests: mask_pii
# ---------------------------------------------------------------------------


class TestMaskPii:
    def test_cnic(self):
        text = "Customer CNIC: 35202-1234567-1"
        masked, types = mask_pii(text)
        assert "35202-1234567-1" not in masked
        assert "*****-*******-*" in masked
        assert "cnic" in types

    def test_phone_03(self):
        text = "Call 03001234567 for details"
        masked, types = mask_pii(text)
        assert "03001234567" not in masked
        assert "***PHONE***" in masked
        assert "phone" in types

    def test_phone_plus92(self):
        text = "Contact +923001234567"
        masked, types = mask_pii(text)
        assert "+923001234567" not in masked
        assert "phone" in types

    def test_email(self):
        text = "Send to user@example.com"
        masked, types = mask_pii(text)
        assert "user@example.com" not in masked
        assert "***EMAIL***" in masked
        assert "email" in types

    def test_no_pii(self):
        text = "Normal transaction description"
        masked, types = mask_pii(text)
        assert masked == text
        assert types == []

    def test_multiple_pii(self):
        text = "CNIC 35202-1234567-1 phone 03001234567"
        masked, types = mask_pii(text)
        assert "cnic" in types
        assert "phone" in types

    def test_empty(self):
        masked, types = mask_pii("")
        assert masked == ""
        assert types == []


# ---------------------------------------------------------------------------
# Tests: compute_fiscal_year
# ---------------------------------------------------------------------------


class TestComputeFiscalYear:
    def test_august_2024(self):
        assert compute_fiscal_year(date(2024, 8, 1)) == "2024-2025"

    def test_july_2024(self):
        assert compute_fiscal_year(date(2024, 7, 1)) == "2024-2025"

    def test_march_2025(self):
        assert compute_fiscal_year(date(2025, 3, 15)) == "2024-2025"

    def test_june_2025(self):
        assert compute_fiscal_year(date(2025, 6, 30)) == "2024-2025"

    def test_january_2024(self):
        assert compute_fiscal_year(date(2024, 1, 1)) == "2023-2024"

    def test_december_2023(self):
        assert compute_fiscal_year(date(2023, 12, 31)) == "2023-2024"


# ---------------------------------------------------------------------------
# Tests: compute_quality_score
# ---------------------------------------------------------------------------


class TestComputeQualityScore:
    def test_perfect_score(self):
        row_data = {
            "transaction_date": date(2024, 1, 1),
            "amount_debit": 1000.0,
            "amount_credit": 0.0,
            "description": "Some description",
            "vendor": "SomeVendor",
            "pii_types_found": [],
        }
        assert compute_quality_score(row_data) == 1.0

    def test_no_data(self):
        row_data = {
            "transaction_date": None,
            "amount_debit": 0.0,
            "amount_credit": 0.0,
            "description": "",
            "vendor": "",
            "pii_types_found": [],
        }
        # Only gets +0.1 for no PII
        assert compute_quality_score(row_data) == 0.1

    def test_date_and_amount_only(self):
        row_data = {
            "transaction_date": date(2024, 1, 1),
            "amount_debit": 500.0,
            "amount_credit": 0.0,
            "description": "",
            "vendor": "",
            "pii_types_found": [],
        }
        # 0.3 + 0.3 + 0.1 = 0.7
        assert compute_quality_score(row_data) == 0.7

    def test_pii_penalty(self):
        row_data = {
            "transaction_date": date(2024, 1, 1),
            "amount_debit": 500.0,
            "amount_credit": 0.0,
            "description": "Has CNIC",
            "vendor": "Vendor",
            "pii_types_found": ["cnic"],
        }
        # 0.3 + 0.3 + 0.2 + 0.1 + 0.0 = 0.9
        assert compute_quality_score(row_data) == 0.9


# ---------------------------------------------------------------------------
# Tests: Full row processing
# ---------------------------------------------------------------------------


class TestProcessRow:
    def test_successful_normalisation(self, conn):
        """Test that a valid bronze row is normalised into silver."""
        raw = {
            "date": "15/03/2024",
            "description": "Electricity bill payment",
            "debit": "PKR 5,000",
            "vendor": "WAPDA",
        }
        bronze_id = str(uuid.uuid4())
        _insert_bronze_row(conn, bronze_id, raw)

        writer = SilverWriter()
        bronze_row = {
            "bronze_id": bronze_id,
            "source_type": "bank_statement",
            "source_software": "excel",
            "raw_content": json.dumps(raw),
            "raw_headers": None,
            "ingestion_batch_id": "batch-001",
        }

        result = writer.process_row(conn, bronze_row)
        assert result == "normalised"

        # Verify silver row
        silver = conn.execute(
            "SELECT * FROM silver_transactions WHERE bronze_id = ?", [bronze_id]
        ).fetchone()
        assert silver is not None

        # Verify bronze status updated
        status = conn.execute(
            "SELECT processing_status FROM bronze_transactions WHERE bronze_id = ?",
            [bronze_id],
        ).fetchone()[0]
        assert status == "normalised"

    def test_quarantine_no_date(self, conn):
        """Row with no parseable date should be quarantined."""
        raw = {
            "description": "Some payment",
            "debit": "1000",
        }
        bronze_id = str(uuid.uuid4())
        _insert_bronze_row(conn, bronze_id, raw)

        writer = SilverWriter()
        bronze_row = {
            "bronze_id": bronze_id,
            "source_type": "bank_statement",
            "source_software": "excel",
            "raw_content": json.dumps(raw),
            "raw_headers": None,
            "ingestion_batch_id": "batch-001",
        }

        result = writer.process_row(conn, bronze_row)
        assert result == "quarantined"

        # Verify quarantine row
        q = conn.execute(
            "SELECT * FROM silver_quarantine WHERE bronze_id = ?", [bronze_id]
        ).fetchone()
        assert q is not None

    def test_quarantine_no_amount(self, conn):
        """Row with no amount and low quality should be quarantined."""
        raw = {
            "date": "invalid-date",
            "description": "",
        }
        bronze_id = str(uuid.uuid4())
        _insert_bronze_row(conn, bronze_id, raw)

        writer = SilverWriter()
        bronze_row = {
            "bronze_id": bronze_id,
            "source_type": "bank_statement",
            "source_software": "excel",
            "raw_content": json.dumps(raw),
            "raw_headers": None,
            "ingestion_batch_id": "batch-001",
        }

        result = writer.process_row(conn, bronze_row)
        assert result == "quarantined"

    def test_pii_masked_in_silver(self, conn):
        """PII in description should be masked in silver."""
        raw = {
            "date": "2024-01-15",
            "description": "Transfer to CNIC 35202-1234567-1",
            "debit": "10000",
            "vendor": "Bank",
        }
        bronze_id = str(uuid.uuid4())
        _insert_bronze_row(conn, bronze_id, raw)

        writer = SilverWriter()
        bronze_row = {
            "bronze_id": bronze_id,
            "source_type": "bank_statement",
            "source_software": "excel",
            "raw_content": json.dumps(raw),
            "raw_headers": None,
            "ingestion_batch_id": "batch-001",
        }

        result = writer.process_row(conn, bronze_row)
        assert result == "normalised"

        silver = conn.execute(
            "SELECT description_masked, pii_masked, pii_types_found FROM silver_transactions WHERE bronze_id = ?",
            [bronze_id],
        ).fetchone()
        assert "35202-1234567-1" not in silver[0]
        assert silver[1] is True
        assert "cnic" in silver[2]

    def test_bronze_status_updated_to_normalised(self, conn):
        """Bronze row status should be updated after normalisation."""
        raw = {
            "date": "2024-06-01",
            "description": "Office supplies",
            "credit": "2500",
            "vendor": "Stationery Shop",
        }
        bronze_id = str(uuid.uuid4())
        _insert_bronze_row(conn, bronze_id, raw)

        writer = SilverWriter()
        bronze_row = {
            "bronze_id": bronze_id,
            "source_type": "bank_statement",
            "source_software": "excel",
            "raw_content": json.dumps(raw),
            "raw_headers": None,
            "ingestion_batch_id": "batch-001",
        }

        writer.process_row(conn, bronze_row)

        status = conn.execute(
            "SELECT processing_status FROM bronze_transactions WHERE bronze_id = ?",
            [bronze_id],
        ).fetchone()[0]
        assert status == "normalised"

    def test_invalid_json_quarantined(self, conn):
        """Invalid JSON in raw_content should quarantine the row."""
        bronze_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO bronze_transactions (
                bronze_id, source_type, source_software, source_file,
                source_file_hash, source_row_number, raw_content,
                ingestion_batch_id, processing_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            [bronze_id, "bank_statement", "excel", "test.xlsx", "abc", 1, "not-json{{{", "batch-001"],
        )

        writer = SilverWriter()
        bronze_row = {
            "bronze_id": bronze_id,
            "source_type": "bank_statement",
            "source_software": "excel",
            "raw_content": "not-json{{{",
            "raw_headers": None,
            "ingestion_batch_id": "batch-001",
        }

        result = writer.process_row(conn, bronze_row)
        assert result == "quarantined"


# ---------------------------------------------------------------------------
# Tests: Batch processing
# ---------------------------------------------------------------------------


class TestProcessBatch:
    def test_batch_multiple_rows(self, conn):
        """Process a batch with multiple rows."""
        batch_id = "batch-multi-001"

        # Good row
        raw1 = {"date": "2024-02-10", "description": "Salary", "credit": "150,000", "vendor": "Employer"}
        _insert_bronze_row(conn, str(uuid.uuid4()), raw1, batch_id)

        # Another good row
        raw2 = {"date": "10/02/2024", "description": "Rent payment", "debit": "50000", "vendor": "Landlord"}
        _insert_bronze_row(conn, str(uuid.uuid4()), raw2, batch_id)

        # Bad row (no date, no amount)
        raw3 = {"notes": "random stuff"}
        _insert_bronze_row(conn, str(uuid.uuid4()), raw3, batch_id)

        writer = SilverWriter()
        result = writer.process_batch(conn, batch_id)

        assert result.rows_processed == 3
        assert result.rows_normalised == 2
        assert result.rows_quarantined == 1
        assert result.duration_ms >= 0

    def test_audit_log_created(self, conn):
        """Audit log entry should be created after batch processing."""
        batch_id = "batch-audit-001"
        raw = {"date": "2024-05-01", "description": "Test", "debit": "100", "vendor": "V"}
        _insert_bronze_row(conn, str(uuid.uuid4()), raw, batch_id)

        writer = SilverWriter()
        writer.process_batch(conn, batch_id)

        logs = conn.execute(
            "SELECT * FROM pipeline_audit_log WHERE batch_id = ?", [batch_id]
        ).fetchall()
        assert len(logs) == 1

        # Check fields
        log = logs[0]
        # log_id, operation, source_layer, batch_id, status, rows_affected, error_detail, duration_ms, created_at
        assert log[1] == "silver_write"      # operation
        assert log[2] == "bronze"            # source_layer
        assert log[3] == batch_id            # batch_id
        assert log[4] == "completed"         # status
        assert log[5] == 1                   # rows_affected

    def test_empty_batch(self, conn):
        """Processing a batch with no pending rows returns zero counts."""
        writer = SilverWriter()
        result = writer.process_batch(conn, "nonexistent-batch")

        assert result.rows_processed == 0
        assert result.rows_normalised == 0
        assert result.rows_quarantined == 0

    def test_fiscal_year_in_silver(self, conn):
        """Verify fiscal year is correctly computed in silver output."""
        batch_id = "batch-fy-001"
        raw = {"date": "2024-08-15", "description": "August payment", "debit": "3000", "vendor": "Shop"}
        bid = str(uuid.uuid4())
        _insert_bronze_row(conn, bid, raw, batch_id)

        writer = SilverWriter()
        writer.process_batch(conn, batch_id)

        silver = conn.execute(
            "SELECT fiscal_year, year_month FROM silver_transactions WHERE bronze_id = ?",
            [bid],
        ).fetchone()
        assert silver[0] == "2024-2025"
        assert silver[1] == "2024-08"

    def test_language_detected_urdu(self, conn):
        """Verify Urdu language detection in silver output."""
        batch_id = "batch-lang-001"
        raw = {"date": "2024-01-01", "description": "بجلی کا بل", "debit": "5000", "vendor": "واپڈا"}
        bid = str(uuid.uuid4())
        _insert_bronze_row(conn, bid, raw, batch_id)

        writer = SilverWriter()
        writer.process_batch(conn, batch_id)

        silver = conn.execute(
            "SELECT language_detected FROM silver_transactions WHERE bronze_id = ?",
            [bid],
        ).fetchone()
        assert silver[0] == "ur"
