"""
Tests for gold_writer — Gold tier of the Medallion Architecture.

Run with:
    python -m pytest test_gold_writer.py -v -p no:asyncio --basetemp="C:\\Users\\123\\Downloads\\Arkin\\temp_tests"
"""

from __future__ import annotations

import json
from datetime import date, datetime

import duckdb
import pytest

from gold_writer import (
    GoldWriter,
    PeriodSummaryBuilder,
    PromotionResult,
    build_embedding_text,
    classify_fbr,
    format_amount,
    format_date_human,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SILVER_DDL = """
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
    pii_masked BOOLEAN DEFAULT FALSE,
    pii_types_found VARCHAR,
    quality_score DOUBLE DEFAULT 0.0,
    normalised_at TIMESTAMP DEFAULT current_timestamp
);
"""

_GOLD_DDL = """
CREATE TABLE IF NOT EXISTS gold_transactions (
    transaction_id VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    silver_id VARCHAR NOT NULL,
    bronze_id VARCHAR NOT NULL,
    transaction_date DATE NOT NULL,
    year_month VARCHAR(7) NOT NULL,
    fiscal_year VARCHAR(9),
    description_masked VARCHAR,
    vendor VARCHAR,
    category VARCHAR,
    subcategory VARCHAR,
    category_confidence DOUBLE DEFAULT 0.0,
    amount_debit DOUBLE DEFAULT 0.0,
    amount_credit DOUBLE DEFAULT 0.0,
    net_amount DOUBLE GENERATED ALWAYS AS (amount_credit - amount_debit) VIRTUAL,
    currency VARCHAR(3) DEFAULT 'PKR',
    embedding_text VARCHAR NOT NULL,
    fbr_category VARCHAR,
    fbr_tax_applicable BOOLEAN DEFAULT FALSE,
    quality_score DOUBLE NOT NULL CHECK (quality_score >= 0.7),
    qdrant_indexed BOOLEAN DEFAULT FALSE,
    gold_version INTEGER DEFAULT 1,
    promoted_at TIMESTAMP DEFAULT current_timestamp
);
"""

_SUMMARY_DDL = """
CREATE TABLE IF NOT EXISTS gold_period_summaries (
    summary_id VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    period_type VARCHAR NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    year_month VARCHAR(7),
    fiscal_year VARCHAR(9),
    total_income DOUBLE DEFAULT 0.0,
    total_expenses DOUBLE DEFAULT 0.0,
    net_amount DOUBLE DEFAULT 0.0,
    transaction_count INTEGER DEFAULT 0,
    category_breakdown VARCHAR,
    anomaly_flag BOOLEAN DEFAULT FALSE,
    vs_prior_period_pct DOUBLE,
    computed_at TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (period_type, period_start)
);
"""

_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_audit_log (
    log_id VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    operation VARCHAR NOT NULL,
    source_layer VARCHAR NOT NULL,
    batch_id VARCHAR,
    status VARCHAR NOT NULL,
    rows_affected INTEGER DEFAULT 0,
    error_detail VARCHAR,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT current_timestamp
);
"""


@pytest.fixture()
def conn():
    """Create an in-memory DuckDB connection with all four tables."""
    c = duckdb.connect(":memory:")
    c.execute(_SILVER_DDL)
    c.execute(_GOLD_DDL)
    c.execute(_SUMMARY_DDL)
    c.execute(_AUDIT_DDL)
    yield c
    c.close()


def _insert_silver(c, silver_id, *, quality_score=0.85, vendor="Shell Clifton",
                   category="Fuel & Transport", amount_debit=5000.0,
                   amount_credit=0.0, tx_date="2024-01-15",
                   year_month="2024-01", fiscal_year="2023-2024",
                   description_masked="Fuel purchase"):
    """Helper to insert a silver row."""
    c.execute(
        """
        INSERT INTO silver_transactions (
            silver_id, bronze_id, transaction_date, year_month, fiscal_year,
            description, description_masked, vendor, category,
            amount_debit, amount_credit, currency, quality_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PKR', ?)
        """,
        [
            silver_id, f"bronze_{silver_id}", tx_date, year_month,
            fiscal_year, "raw desc", description_masked, vendor, category,
            amount_debit, amount_credit, quality_score,
        ],
    )


# ===========================================================================
# format_amount tests
# ===========================================================================

class TestFormatAmount:
    def test_basic(self):
        assert format_amount(5000, "PKR") == "PKR 5,000"

    def test_large_number(self):
        assert format_amount(1234567, "PKR") == "PKR 1,234,567"

    def test_small_number(self):
        assert format_amount(50, "USD") == "USD 50"

    def test_zero(self):
        assert format_amount(0, "PKR") == "PKR 0"

    def test_decimal_rounds(self):
        assert format_amount(5000.75, "PKR") == "PKR 5,001"


# ===========================================================================
# format_date_human tests
# ===========================================================================

class TestFormatDateHuman:
    def test_date_object(self):
        assert format_date_human(date(2024, 1, 15)) == "15 Jan 2024"

    def test_datetime_object(self):
        assert format_date_human(datetime(2024, 12, 25, 10, 30)) == "25 Dec 2024"

    def test_string_iso(self):
        assert format_date_human("2024-01-15") == "15 Jan 2024"

    def test_none(self):
        assert format_date_human(None) == "Unknown date"

    def test_unparseable_string(self):
        assert format_date_human("not-a-date") == "not-a-date"


# ===========================================================================
# classify_fbr tests
# ===========================================================================

class TestClassifyFbr:
    def test_rent(self):
        assert classify_fbr("Rent") == ("Section 155 - Rent", True)

    def test_rent_case_insensitive(self):
        assert classify_fbr("Office Rent") == ("Section 155 - Rent", True)

    def test_salary(self):
        assert classify_fbr("Salary") == ("Section 149 - Salary", True)

    def test_wages(self):
        assert classify_fbr("Daily Wages") == ("Section 149 - Salary", True)

    def test_fuel(self):
        assert classify_fbr("Fuel & Transport") == ("Section 153 - Goods", True)

    def test_supplies(self):
        assert classify_fbr("Office Supplies") == ("Section 153 - Goods", True)

    def test_goods(self):
        assert classify_fbr("Goods Purchase") == ("Section 153 - Goods", True)

    def test_consulting(self):
        assert classify_fbr("Consulting Fees") == ("Section 153 - Services", True)

    def test_legal(self):
        assert classify_fbr("Legal Services") == ("Section 153 - Services", True)

    def test_services(self):
        assert classify_fbr("Professional Services") == ("Section 153 - Services", True)

    def test_unknown(self):
        assert classify_fbr("Miscellaneous") == (None, False)

    def test_none(self):
        assert classify_fbr(None) == (None, False)

    def test_empty(self):
        assert classify_fbr("") == (None, False)


# ===========================================================================
# build_embedding_text tests
# ===========================================================================

class TestBuildEmbeddingText:
    def test_debit_with_vendor_and_category(self):
        row = {
            "transaction_date": date(2024, 1, 15),
            "currency": "PKR",
            "amount_debit": 5000.0,
            "amount_credit": 0.0,
            "vendor": "Shell Clifton",
            "category": "Fuel & Transport",
            "description_masked": "Fuel purchase",
        }
        text = build_embedding_text(row)
        assert text == "On 15 Jan 2024, PKR 5,000 was paid to Shell Clifton — Fuel & Transport"

    def test_credit_with_vendor_and_category(self):
        row = {
            "transaction_date": date(2024, 2, 10),
            "currency": "PKR",
            "amount_debit": 0.0,
            "amount_credit": 100000.0,
            "vendor": "Acme Corp",
            "category": "Revenue",
        }
        text = build_embedding_text(row)
        assert text == "On 10 Feb 2024, PKR 100,000 was received from Acme Corp — Revenue"

    def test_debit_without_vendor(self):
        row = {
            "transaction_date": date(2024, 1, 15),
            "currency": "PKR",
            "amount_debit": 5000.0,
            "amount_credit": 0.0,
            "vendor": None,
            "category": "Utilities",
        }
        text = build_embedding_text(row)
        assert text == "On 15 Jan 2024, PKR 5,000 was debited — Utilities"

    def test_credit_without_vendor(self):
        row = {
            "transaction_date": date(2024, 3, 1),
            "currency": "PKR",
            "amount_debit": 0.0,
            "amount_credit": 25000.0,
            "vendor": None,
            "category": "Revenue",
        }
        text = build_embedding_text(row)
        assert text == "On 1 Mar 2024, PKR 25,000 was credited — Revenue"

    def test_without_category(self):
        row = {
            "transaction_date": date(2024, 1, 15),
            "currency": "PKR",
            "amount_debit": 5000.0,
            "amount_credit": 0.0,
            "vendor": "Shell Clifton",
            "category": None,
        }
        text = build_embedding_text(row)
        assert text == "On 15 Jan 2024, PKR 5,000 was paid to Shell Clifton"
        assert "—" not in text

    def test_without_vendor_or_category(self):
        row = {
            "transaction_date": date(2024, 1, 15),
            "currency": "PKR",
            "amount_debit": 3000.0,
            "amount_credit": 0.0,
            "vendor": None,
            "category": None,
        }
        text = build_embedding_text(row)
        assert text == "On 15 Jan 2024, PKR 3,000 was debited"

    def test_amount_formatting_in_text(self):
        row = {
            "transaction_date": date(2024, 1, 15),
            "currency": "PKR",
            "amount_debit": 5000.0,
            "amount_credit": 0.0,
            "vendor": "Test",
            "category": "Test",
        }
        text = build_embedding_text(row)
        assert "PKR 5,000" in text
        assert "5000" not in text

    def test_date_formatting_in_text(self):
        row = {
            "transaction_date": date(2024, 1, 15),
            "currency": "PKR",
            "amount_debit": 100.0,
            "amount_credit": 0.0,
            "vendor": "X",
            "category": "Y",
        }
        text = build_embedding_text(row)
        assert text.startswith("On 15 Jan 2024,")


# ===========================================================================
# Quality gate tests
# ===========================================================================

class TestQualityGate:
    def test_quality_085_promoted(self, conn):
        _insert_silver(conn, "s1", quality_score=0.85)
        writer = GoldWriter()
        row = _fetch_silver_dict(conn, "s1")
        assert writer.promote_row(conn, row) is True
        assert _gold_count(conn) == 1

    def test_quality_exact_07_promoted(self, conn):
        _insert_silver(conn, "s2", quality_score=0.7)
        writer = GoldWriter()
        row = _fetch_silver_dict(conn, "s2")
        assert writer.promote_row(conn, row) is True
        assert _gold_count(conn) == 1

    def test_quality_05_skipped(self, conn):
        _insert_silver(conn, "s3", quality_score=0.5)
        writer = GoldWriter()
        row = _fetch_silver_dict(conn, "s3")
        assert writer.promote_row(conn, row) is False
        assert _gold_count(conn) == 0

    def test_quality_03_skipped(self, conn):
        _insert_silver(conn, "s4", quality_score=0.3)
        writer = GoldWriter()
        row = _fetch_silver_dict(conn, "s4")
        assert writer.promote_row(conn, row) is False
        assert _gold_count(conn) == 0


# ===========================================================================
# Batch promotion tests
# ===========================================================================

class TestBatchPromotion:
    def test_promotes_multiple_rows(self, conn):
        _insert_silver(conn, "batch1_001", quality_score=0.85)
        _insert_silver(conn, "batch1_002", quality_score=0.9)
        writer = GoldWriter()
        result = writer.promote_batch(conn, "batch1")
        assert result.rows_promoted == 2
        assert result.rows_eligible == 2
        assert _gold_count(conn) == 2

    def test_mixed_batch(self, conn):
        _insert_silver(conn, "batch2_001", quality_score=0.85)
        _insert_silver(conn, "batch2_002", quality_score=0.5)
        _insert_silver(conn, "batch2_003", quality_score=0.3)
        _insert_silver(conn, "batch2_004", quality_score=0.75)
        writer = GoldWriter()
        result = writer.promote_batch(conn, "batch2")
        assert result.rows_eligible == 2
        assert result.rows_promoted == 2
        assert result.rows_skipped == 2
        assert _gold_count(conn) == 2

    def test_audit_log_created(self, conn):
        _insert_silver(conn, "batch3_001", quality_score=0.85)
        writer = GoldWriter()
        writer.promote_batch(conn, "batch3")
        logs = conn.execute(
            "SELECT operation, source_layer, status, rows_affected "
            "FROM pipeline_audit_log WHERE batch_id = 'batch3'"
        ).fetchall()
        assert len(logs) == 1
        op, layer, status, affected = logs[0]
        assert op == "promote_batch"
        assert layer == "gold"
        assert status == "success"
        assert affected == 1

    def test_promotion_result_counts(self, conn):
        _insert_silver(conn, "batch4_001", quality_score=0.9)
        _insert_silver(conn, "batch4_002", quality_score=0.4)
        writer = GoldWriter()
        result = writer.promote_batch(conn, "batch4")
        assert isinstance(result, PromotionResult)
        assert result.rows_eligible == 1
        assert result.rows_promoted == 1
        assert result.rows_skipped == 1
        assert result.errors == []
        assert result.duration_ms >= 0

    def test_empty_batch(self, conn):
        writer = GoldWriter()
        result = writer.promote_batch(conn, "nonexistent")
        assert result.rows_promoted == 0
        assert result.rows_eligible == 0
        assert result.rows_skipped == 0


# ===========================================================================
# Gold row content tests
# ===========================================================================

class TestGoldRowContent:
    def test_embedding_text_stored(self, conn):
        _insert_silver(conn, "g1", quality_score=0.85, vendor="Shell Clifton",
                       category="Fuel & Transport")
        writer = GoldWriter()
        row = _fetch_silver_dict(conn, "g1")
        writer.promote_row(conn, row)
        gold = conn.execute(
            "SELECT embedding_text FROM gold_transactions WHERE silver_id = 'g1'"
        ).fetchone()
        assert gold is not None
        assert "Shell Clifton" in gold[0]
        assert "Fuel & Transport" in gold[0]

    def test_fbr_category_stored(self, conn):
        _insert_silver(conn, "g2", quality_score=0.85, category="Rent")
        writer = GoldWriter()
        row = _fetch_silver_dict(conn, "g2")
        writer.promote_row(conn, row)
        gold = conn.execute(
            "SELECT fbr_category, fbr_tax_applicable FROM gold_transactions WHERE silver_id = 'g2'"
        ).fetchone()
        assert gold[0] == "Section 155 - Rent"
        assert gold[1] is True


# ===========================================================================
# PeriodSummaryBuilder tests
# ===========================================================================

class TestPeriodSummary:
    def _seed_gold(self, conn):
        """Seed gold_transactions directly for summary testing."""
        writer = GoldWriter()
        # January — two transactions
        _insert_silver(conn, "sum_jan_1", quality_score=0.85,
                       amount_debit=5000, amount_credit=0,
                       tx_date="2024-01-10", year_month="2024-01",
                       category="Fuel & Transport")
        _insert_silver(conn, "sum_jan_2", quality_score=0.85,
                       amount_debit=0, amount_credit=20000,
                       tx_date="2024-01-15", year_month="2024-01",
                       category="Revenue")
        # February — one transaction
        _insert_silver(conn, "sum_feb_1", quality_score=0.85,
                       amount_debit=80000, amount_credit=0,
                       tx_date="2024-02-01", year_month="2024-02",
                       category="Rent")
        for sid in ["sum_jan_1", "sum_jan_2", "sum_feb_1"]:
            row = _fetch_silver_dict(conn, sid)
            writer.promote_row(conn, row)

    def test_monthly_summary_computed(self, conn):
        self._seed_gold(conn)
        builder = PeriodSummaryBuilder()
        count = builder.build_monthly_summaries(conn)
        assert count == 2

    def test_january_values(self, conn):
        self._seed_gold(conn)
        PeriodSummaryBuilder().build_monthly_summaries(conn)
        row = conn.execute(
            "SELECT total_income, total_expenses, transaction_count "
            "FROM gold_period_summaries WHERE year_month = '2024-01'"
        ).fetchone()
        assert row is not None
        assert row[0] == 20000.0   # total_income (credit)
        assert row[1] == 5000.0    # total_expenses (debit)
        assert row[2] == 2         # transaction_count

    def test_category_breakdown_json(self, conn):
        self._seed_gold(conn)
        PeriodSummaryBuilder().build_monthly_summaries(conn)
        row = conn.execute(
            "SELECT category_breakdown FROM gold_period_summaries "
            "WHERE year_month = '2024-01'"
        ).fetchone()
        breakdown = json.loads(row[0])
        assert isinstance(breakdown, dict)
        assert "Fuel & Transport" in breakdown
        assert "Revenue" in breakdown

    def test_anomaly_detection(self, conn):
        self._seed_gold(conn)
        PeriodSummaryBuilder().build_monthly_summaries(conn)
        # Jan net = 20000 - 5000 = 15000; Feb net = 0 - 80000 = -80000
        # Change = (-80000 - 15000) / 15000 * 100 = -633%  => anomaly
        feb = conn.execute(
            "SELECT anomaly_flag, vs_prior_period_pct "
            "FROM gold_period_summaries WHERE year_month = '2024-02'"
        ).fetchone()
        assert feb[0] is True
        assert feb[1] is not None
        assert abs(feb[1]) > 50

    def test_multiple_months_present(self, conn):
        self._seed_gold(conn)
        PeriodSummaryBuilder().build_monthly_summaries(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM gold_period_summaries"
        ).fetchone()[0]
        assert count == 2

    def test_idempotent(self, conn):
        self._seed_gold(conn)
        builder = PeriodSummaryBuilder()
        builder.build_monthly_summaries(conn)
        builder.build_monthly_summaries(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM gold_period_summaries"
        ).fetchone()[0]
        assert count == 2


# ===========================================================================
# Helpers
# ===========================================================================

def _fetch_silver_dict(conn, silver_id: str) -> dict:
    """Fetch a silver row as a dict."""
    row = conn.execute(
        "SELECT * FROM silver_transactions WHERE silver_id = ?",
        [silver_id],
    ).fetchone()
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def _gold_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM gold_transactions").fetchone()[0]
