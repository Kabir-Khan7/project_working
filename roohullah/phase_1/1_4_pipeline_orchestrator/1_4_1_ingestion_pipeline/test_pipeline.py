"""
Tests for 1.4.1 — Ingestion Pipeline Orchestrator

Run with:
    python -m pytest test_pipeline.py -v -p no:asyncio --basetemp="C:\\Users\\123\\Downloads\\Arkin\\temp_tests"
"""

from __future__ import annotations

import json
import os
import textwrap

import pytest

from pipeline import IngestionPipeline, PipelineResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
STANDARD_CSV = textwrap.dedent("""\
    Date,Description,Party,Amount,Type
    15/01/2024,Rent payment,Landlord,50000,debit
    16/01/2024,Sale to ABC Co,ABC Co,80000,credit
    17/01/2024,Electricity bill,,3500,debit
    18/01/2024,Payment with CNIC 12345-1234567-1,Ali Khan,5000,debit
    20/01/2024,,Unknown,1000,debit
""")

URDU_CSV = textwrap.dedent("""\
    تاریخ,تفصیل,نام,رقم
    15/01/2024,کرایہ ادائیگی,مالک مکان,50000
""")


@pytest.fixture
def csv_file(tmp_path):
    """Write the standard CSV to a temp file and return the path."""
    p = tmp_path / "test_data.csv"
    p.write_text(STANDARD_CSV, encoding="utf-8")
    return str(p)


@pytest.fixture
def urdu_csv_file(tmp_path):
    """Write the Urdu CSV to a temp file and return the path."""
    p = tmp_path / "urdu_data.csv"
    p.write_text(URDU_CSV, encoding="utf-8")
    return str(p)


@pytest.fixture
def empty_csv_file(tmp_path):
    """Write an empty CSV (header only) to a temp file."""
    p = tmp_path / "empty_data.csv"
    p.write_text("Date,Description,Party,Amount,Type\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def pipeline():
    """Create a fresh in-memory pipeline for each test."""
    pl = IngestionPipeline(db_path=":memory:")
    yield pl
    pl.close()


@pytest.fixture
def ingested(pipeline, csv_file):
    """Pipeline with the standard CSV already ingested."""
    result = pipeline.ingest_file(csv_file)
    return pipeline, result


# ---------------------------------------------------------------------------
# Bronze stage tests
# ---------------------------------------------------------------------------
class TestBronze:
    def test_csv_parsed_to_bronze(self, ingested):
        pl, result = ingested
        assert result.bronze_rows == 5

    def test_raw_content_preserves_columns(self, ingested):
        pl, _ = ingested
        row = pl.conn.execute(
            "SELECT raw_content FROM bronze_transactions LIMIT 1"
        ).fetchone()
        content = json.loads(row[0])
        assert "Date" in content
        assert "Description" in content
        assert "Party" in content

    def test_batch_id_assigned(self, ingested):
        pl, result = ingested
        assert result.batch_id is not None
        rows = pl.conn.execute(
            "SELECT DISTINCT ingestion_batch_id FROM bronze_transactions"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == result.batch_id

    def test_duplicate_file_rejected(self, pipeline, csv_file):
        r1 = pipeline.ingest_file(csv_file)
        assert r1.bronze_rows == 5
        r2 = pipeline.ingest_file(csv_file)
        assert r2.bronze_rows == 0
        assert any("Duplicate" in e for e in r2.errors)

    def test_row_count_matches(self, ingested):
        pl, _ = ingested
        count = pl.conn.execute(
            "SELECT COUNT(*) FROM bronze_transactions"
        ).fetchone()[0]
        assert count == 5

    def test_processing_status_initial(self, pipeline, csv_file):
        """After full pipeline, no rows should remain 'pending'."""
        pipeline.ingest_file(csv_file)
        pending = pipeline.conn.execute(
            "SELECT COUNT(*) FROM bronze_transactions WHERE processing_status = 'pending'"
        ).fetchone()[0]
        assert pending == 0


# ---------------------------------------------------------------------------
# Silver stage tests
# ---------------------------------------------------------------------------
class TestSilver:
    def test_date_parsed_correctly(self, ingested):
        pl, _ = ingested
        row = pl.conn.execute(
            "SELECT transaction_date FROM silver_transactions ORDER BY transaction_date LIMIT 1"
        ).fetchone()
        assert row is not None
        # Should be 2024-01-15
        assert str(row[0]) == "2024-01-15"

    def test_amounts_extracted(self, ingested):
        pl, _ = ingested
        debit_sum = pl.conn.execute(
            "SELECT SUM(amount_debit) FROM silver_transactions"
        ).fetchone()[0]
        credit_sum = pl.conn.execute(
            "SELECT SUM(amount_credit) FROM silver_transactions"
        ).fetchone()[0]
        # 50000+3500+5000+1000 debit = 59500, 80000 credit
        assert debit_sum == 59500.0
        assert credit_sum == 80000.0

    def test_pii_masked_cnic(self, ingested):
        pl, _ = ingested
        row = pl.conn.execute(
            "SELECT description_masked, pii_masked, pii_types_found "
            "FROM silver_transactions WHERE description LIKE '%CNIC%'"
        ).fetchone()
        assert row is not None
        assert "[CNIC]" in row[0]
        assert "12345-1234567-1" not in row[0]
        assert row[1] is True
        assert "CNIC" in row[2]

    def test_quality_score_computed(self, ingested):
        pl, _ = ingested
        rows = pl.conn.execute(
            "SELECT quality_score FROM silver_transactions"
        ).fetchall()
        for row in rows:
            assert row[0] > 0.0
            assert row[0] <= 1.0

    def test_low_quality_quarantined(self, ingested):
        pl, _ = ingested
        # Row 5 has no description ("") and vendor "Unknown" — but has date+amount+vendor
        # so quality = 0.3+0.3+0.1+0.1 = 0.8 — it passes.
        # All 5 rows should pass quarantine threshold of 0.3.
        quarantine = pl.conn.execute(
            "SELECT COUNT(*) FROM silver_quarantine"
        ).fetchone()[0]
        assert quarantine == 0

    def test_fiscal_year_correct(self, ingested):
        pl, _ = ingested
        # January 2024 -> fiscal year 2023-2024
        fy = pl.conn.execute(
            "SELECT fiscal_year FROM silver_transactions WHERE transaction_date = '2024-01-15'"
        ).fetchone()
        assert fy is not None
        assert fy[0] == "2023-2024"

    def test_year_month_correct(self, ingested):
        pl, _ = ingested
        ym = pl.conn.execute(
            "SELECT year_month FROM silver_transactions WHERE transaction_date = '2024-01-15'"
        ).fetchone()
        assert ym is not None
        assert ym[0] == "2024-01"

    def test_vendor_extracted(self, ingested):
        pl, _ = ingested
        vendors = pl.conn.execute(
            "SELECT vendor FROM silver_transactions ORDER BY transaction_date"
        ).fetchall()
        assert vendors[0][0] == "Landlord"
        assert vendors[1][0] == "ABC Co"

    def test_category_inferred(self, ingested):
        pl, _ = ingested
        # "Rent payment" should get Rental category
        cat = pl.conn.execute(
            "SELECT category FROM silver_transactions WHERE description = 'Rent payment'"
        ).fetchone()
        assert cat is not None
        assert "Rental" in cat[0]

    def test_electricity_category(self, ingested):
        pl, _ = ingested
        cat = pl.conn.execute(
            "SELECT category FROM silver_transactions WHERE description = 'Electricity bill'"
        ).fetchone()
        assert cat is not None
        assert "Utilities" in cat[0]


# ---------------------------------------------------------------------------
# Gold stage tests
# ---------------------------------------------------------------------------
class TestGold:
    def test_high_quality_promoted(self, ingested):
        pl, result = ingested
        assert result.gold_rows > 0
        gold_count = pl.conn.execute(
            "SELECT COUNT(*) FROM gold_transactions"
        ).fetchone()[0]
        assert gold_count == result.gold_rows

    def test_embedding_text_generated(self, ingested):
        pl, _ = ingested
        row = pl.conn.execute(
            "SELECT embedding_text FROM gold_transactions LIMIT 1"
        ).fetchone()
        assert row is not None
        assert "On " in row[0]
        assert "PKR" in row[0]

    def test_quality_gate_enforced(self, ingested):
        pl, _ = ingested
        below = pl.conn.execute(
            "SELECT COUNT(*) FROM gold_transactions WHERE quality_score < 0.7"
        ).fetchone()[0]
        assert below == 0

    def test_fbr_classification_applied(self, ingested):
        pl, _ = ingested
        row = pl.conn.execute(
            "SELECT fbr_category, fbr_tax_applicable "
            "FROM gold_transactions WHERE description_masked LIKE '%Rent%'"
        ).fetchone()
        assert row is not None
        assert row[0] is not None  # has an FBR category
        assert isinstance(row[1], bool)

    def test_gold_has_bronze_and_silver_ids(self, ingested):
        pl, _ = ingested
        row = pl.conn.execute(
            "SELECT silver_id, bronze_id FROM gold_transactions LIMIT 1"
        ).fetchone()
        assert row[0] is not None
        assert row[1] is not None


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------
class TestFullPipeline:
    def test_end_to_end(self, ingested):
        pl, result = ingested
        assert result.success is True
        assert result.bronze_rows == 5
        assert result.silver_rows > 0
        assert result.gold_rows > 0

    def test_stats_correct(self, ingested):
        pl, result = ingested
        stats = pl.get_stats()
        assert stats["bronze_transactions"] == 5
        assert stats["silver_transactions"] == result.silver_rows
        assert stats["gold_transactions"] == result.gold_rows

    def test_pipeline_result_numbers(self, ingested):
        _, result = ingested
        assert result.bronze_rows == 5
        assert result.silver_rows + result.quarantined_rows == 5
        assert result.duration_ms >= 0

    def test_audit_log_has_entries(self, ingested):
        pl, _ = ingested
        count = pl.conn.execute(
            "SELECT COUNT(*) FROM pipeline_audit_log"
        ).fetchone()[0]
        # At least bronze_ingest, silver_normalise, gold_promote, ingest_file
        assert count >= 4

    def test_empty_csv(self, pipeline, empty_csv_file):
        result = pipeline.ingest_file(empty_csv_file)
        assert result.bronze_rows == 0
        assert result.silver_rows == 0
        assert result.gold_rows == 0

    def test_urdu_csv_columns(self, pipeline, urdu_csv_file):
        result = pipeline.ingest_file(urdu_csv_file)
        assert result.bronze_rows == 1
        assert result.silver_rows >= 1
        # Check language detected
        lang = pipeline.conn.execute(
            "SELECT language_detected FROM silver_transactions LIMIT 1"
        ).fetchone()
        assert lang is not None
        assert lang[0] == "ur"

    def test_urdu_csv_date_parsed(self, pipeline, urdu_csv_file):
        pipeline.ingest_file(urdu_csv_file)
        row = pipeline.conn.execute(
            "SELECT transaction_date FROM silver_transactions LIMIT 1"
        ).fetchone()
        assert row is not None
        assert str(row[0]) == "2024-01-15"

    def test_multiple_files_different_batches(self, pipeline, tmp_path):
        f1 = tmp_path / "file1.csv"
        f1.write_text(
            "Date,Description,Party,Amount,Type\n"
            "01/02/2024,Test one,Vendor A,1000,debit\n",
            encoding="utf-8",
        )
        f2 = tmp_path / "file2.csv"
        f2.write_text(
            "Date,Description,Party,Amount,Type\n"
            "02/02/2024,Test two,Vendor B,2000,credit\n",
            encoding="utf-8",
        )
        r1 = pipeline.ingest_file(str(f1))
        r2 = pipeline.ingest_file(str(f2))
        assert r1.batch_id != r2.batch_id
        stats = pipeline.get_stats()
        assert stats["bronze_transactions"] == 2


# ---------------------------------------------------------------------------
# Pipeline summary tests
# ---------------------------------------------------------------------------
class TestSummary:
    def test_summary_is_human_readable(self, ingested):
        _, result = ingested
        assert isinstance(result.summary, str)
        assert len(result.summary) > 20
        assert "bronze" in result.summary.lower() or "silver" in result.summary.lower()
        assert result.file_name in result.summary

    def test_summary_contains_counts(self, ingested):
        _, result = ingested
        assert str(result.bronze_rows) in result.summary
        assert str(result.gold_rows) in result.summary
