"""
Tests for 1.0.1 Medallion Architecture (DuckDB)
-------------------------------------------------
Run: python -m pytest test_db_manager.py -v
"""

import json
import os
import tempfile

import pytest

from db_manager import DatabaseManager


@pytest.fixture
def db(tmp_path):
    """Fresh database for each test."""
    db_path = str(tmp_path / "test.db")
    manager = DatabaseManager(db_path=db_path)
    manager.initialise()
    yield manager
    manager.close()


# ── Initialization ───────────────────────────────────────────────────────────

class TestInitialization:
    def test_db_file_created(self, tmp_path):
        db_path = str(tmp_path / "test_init.db")
        manager = DatabaseManager(db_path=db_path)
        manager.initialise()
        assert os.path.exists(db_path)
        manager.close()

    def test_idempotent_init(self, db):
        """Calling initialise() twice should not destroy data."""
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO bronze_transactions
                    (source_type, source_software, source_file,
                     source_file_hash, raw_content, ingestion_batch_id)
                VALUES ('csv', 'manual_excel', 'test.csv',
                        'abc123', '{"a":1}', 'batch-1')
            """)
        # Re-initialise
        db.initialise()
        stats = db.get_table_stats()
        assert stats["bronze_transactions"] == 1  # Data survived

    def test_all_tables_created(self, db):
        stats = db.get_table_stats()
        expected_tables = [
            "bronze_transactions",
            "bronze_schema_mappings",
            "silver_transactions",
            "silver_quarantine",
            "gold_transactions",
            "gold_period_summaries",
            "pipeline_audit_log",
        ]
        for table in expected_tables:
            assert table in stats, f"Table {table} not found"

    def test_healthy_after_init(self, db):
        assert db.is_healthy() is True

    def test_not_healthy_before_init(self, tmp_path):
        manager = DatabaseManager(db_path=str(tmp_path / "noinit.db"))
        assert manager.is_healthy() is False

    def test_creates_storage_directory(self, tmp_path):
        nested = str(tmp_path / "deep" / "nested" / "test.db")
        manager = DatabaseManager(db_path=nested)
        manager.initialise()
        assert os.path.exists(nested)
        manager.close()


# ── Bronze Layer ─────────────────────────────────────────────────────────────

class TestBronzeLayer:
    def test_insert_bronze_row(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO bronze_transactions
                    (source_type, source_software, source_file,
                     source_file_hash, raw_content, ingestion_batch_id)
                VALUES ('xlsx', 'tally', 'daybook.xlsx',
                        'hash123', '{"Date":"01/01/2024","Amount":"5000"}',
                        'batch-001')
            """)
        stats = db.get_table_stats()
        assert stats["bronze_transactions"] == 1

    def test_bronze_uuid_generated(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO bronze_transactions
                    (source_type, source_software, source_file,
                     source_file_hash, raw_content, ingestion_batch_id)
                VALUES ('csv', 'manual_excel', 'test.csv',
                        'hash456', '{"a":1}', 'batch-002')
            """)
            result = conn.execute(
                "SELECT bronze_id FROM bronze_transactions"
            ).fetchone()
        assert result[0] is not None
        assert len(result[0]) > 10  # UUID format

    def test_bronze_default_status_pending(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO bronze_transactions
                    (source_type, source_software, source_file,
                     source_file_hash, raw_content, ingestion_batch_id)
                VALUES ('csv', 'manual_excel', 'test.csv',
                        'hash789', '{"a":1}', 'batch-003')
            """)
            result = conn.execute(
                "SELECT processing_status FROM bronze_transactions"
            ).fetchone()
        assert result[0] == "pending"

    def test_bronze_preserves_json(self, db):
        original = {"Taareekh": "15/01/2024", "Raqam": "5000", "Tafseelat": "Rent"}
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO bronze_transactions
                    (source_type, source_software, source_file,
                     source_file_hash, raw_content, ingestion_batch_id)
                VALUES ('xlsx', 'manual_excel', 'test.xlsx',
                        'hashjson', ?, 'batch-004')
            """, [json.dumps(original, ensure_ascii=False)])
            result = conn.execute(
                "SELECT raw_content FROM bronze_transactions WHERE source_file_hash = 'hashjson'"
            ).fetchone()
        stored = json.loads(result[0]) if isinstance(result[0], str) else result[0]
        assert stored["Taareekh"] == "15/01/2024"
        assert stored["Raqam"] == "5000"

    def test_bronze_batch_grouping(self, db):
        with db.connection() as conn:
            for i in range(5):
                conn.execute("""
                    INSERT INTO bronze_transactions
                        (source_type, source_software, source_file,
                         source_file_hash, source_row_number,
                         raw_content, ingestion_batch_id)
                    VALUES ('csv', 'manual_excel', 'big_file.csv',
                            'batchhash', ?, ?, 'batch-group-1')
                """, [i + 1, json.dumps({"row": i})])
            count = conn.execute(
                "SELECT COUNT(*) FROM bronze_transactions WHERE ingestion_batch_id = 'batch-group-1'"
            ).fetchone()
        assert count[0] == 5


# ── Silver Layer ─────────────────────────────────────────────────────────────

class TestSilverLayer:
    def test_insert_silver_row(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO silver_transactions
                    (bronze_id, transaction_date, year_month,
                     description, amount_debit, amount_credit, currency)
                VALUES ('bronze-001', '2024-01-15', '2024-01',
                        'Rent payment', 50000, 0, 'PKR')
            """)
        stats = db.get_table_stats()
        assert stats["silver_transactions"] == 1

    def test_silver_net_amount_virtual(self, db):
        """net_amount = credit - debit (computed automatically)."""
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO silver_transactions
                    (bronze_id, transaction_date, year_month,
                     amount_debit, amount_credit)
                VALUES ('bronze-net', '2024-01-15', '2024-01', 5000, 80000)
            """)
            result = conn.execute(
                "SELECT net_amount FROM silver_transactions WHERE bronze_id = 'bronze-net'"
            ).fetchone()
        assert result[0] == 75000.0  # 80000 - 5000

    def test_silver_quarantine(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO silver_quarantine
                    (bronze_id, reason, error_detail)
                VALUES ('bronze-bad', 'date_parse_failed',
                        'Could not parse date: 32/13/2024')
            """)
        stats = db.get_table_stats()
        assert stats["silver_quarantine"] == 1

    def test_silver_fiscal_year(self, db):
        """Pakistani fiscal year: July 2024 → June 2025 = '2024-2025'."""
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO silver_transactions
                    (bronze_id, transaction_date, year_month,
                     fiscal_year, amount_debit, amount_credit)
                VALUES ('bronze-fy', '2024-08-15', '2024-08',
                        '2024-2025', 10000, 0)
            """)
            result = conn.execute(
                "SELECT fiscal_year FROM silver_transactions WHERE bronze_id = 'bronze-fy'"
            ).fetchone()
        assert result[0] == "2024-2025"


# ── Gold Layer ───────────────────────────────────────────────────────────────

class TestGoldLayer:
    def test_insert_gold_row(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO gold_transactions
                    (silver_id, bronze_id, transaction_date, year_month,
                     description_masked, vendor, category,
                     amount_debit, amount_credit,
                     embedding_text, quality_score)
                VALUES ('silver-001', 'bronze-001', '2024-01-15', '2024-01',
                        'Rent payment to [VENDOR]', 'Shell', 'Fuel',
                        5000, 0,
                        'On 15 Jan 2024, PKR 5,000 was paid to Shell — Fuel',
                        0.85)
            """)
        stats = db.get_table_stats()
        assert stats["gold_transactions"] == 1

    def test_gold_rejects_low_quality(self, db):
        """Quality gate: score < 0.7 should be REJECTED by CHECK constraint."""
        with db.connection() as conn:
            with pytest.raises(Exception):  # DuckDB raises constraint violation
                conn.execute("""
                    INSERT INTO gold_transactions
                        (silver_id, bronze_id, transaction_date, year_month,
                         embedding_text, quality_score)
                    VALUES ('s-bad', 'b-bad', '2024-01-15', '2024-01',
                            'Low quality row', 0.3)
                """)

    def test_gold_accepts_exact_threshold(self, db):
        """quality_score = 0.7 should pass the gate."""
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO gold_transactions
                    (silver_id, bronze_id, transaction_date, year_month,
                     embedding_text, quality_score)
                VALUES ('s-ok', 'b-ok', '2024-01-15', '2024-01',
                        'Threshold row', 0.7)
            """)
        stats = db.get_table_stats()
        assert stats["gold_transactions"] == 1

    def test_gold_net_amount_virtual(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO gold_transactions
                    (silver_id, bronze_id, transaction_date, year_month,
                     embedding_text, quality_score,
                     amount_debit, amount_credit)
                VALUES ('s-net', 'b-net', '2024-01-15', '2024-01',
                        'Net test', 0.9, 3000, 10000)
            """)
            result = conn.execute(
                "SELECT net_amount FROM gold_transactions WHERE silver_id = 's-net'"
            ).fetchone()
        assert result[0] == 7000.0  # 10000 - 3000

    def test_gold_period_summary(self, db):
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO gold_period_summaries
                    (period_type, period_start, period_end, year_month,
                     total_income, total_expenses, transaction_count,
                     category_breakdown)
                VALUES ('monthly', '2024-01-01', '2024-01-31', '2024-01',
                        500000, 200000, 45,
                        '{"Fuel": 50000, "Rent": 80000, "Utilities": 70000}')
            """)
        stats = db.get_table_stats()
        assert stats["gold_period_summaries"] == 1


# ── Audit Log ────────────────────────────────────────────────────────────────

class TestAuditLog:
    def test_log_operation(self, db):
        db.log_operation(
            "bronze_insert", "bronze", "success",
            batch_id="batch-audit", rows_affected=50, duration_ms=120,
        )
        stats = db.get_table_stats()
        assert stats["pipeline_audit_log"] == 1

    def test_log_failure_non_fatal(self, db):
        """Audit logging should never crash the pipeline."""
        db.log_operation(
            "silver_normalise", "silver", "failed",
            error_detail="Date parse failed for 5 rows",
            rows_affected=0, duration_ms=45,
        )
        with db.connection() as conn:
            result = conn.execute(
                "SELECT status, error_detail FROM pipeline_audit_log"
            ).fetchone()
        assert result[0] == "failed"
        assert "Date parse" in result[1]

    def test_log_without_init_does_not_crash(self, tmp_path):
        """Logging before init should silently skip."""
        manager = DatabaseManager(db_path=str(tmp_path / "noinit.db"))
        manager.log_operation("test", "bronze", "success")  # should not raise


# ── Schema Mapping Memory ────────────────────────────────────────────────────

class TestSchemaMappings:
    def test_save_and_retrieve_mapping(self, db):
        db.save_mapping("tally", "Particulars", "description", confidence=0.95)
        result = db.get_mapping("tally", "Particulars")
        assert result is not None
        assert result["mapped_to"] == "description"
        assert result["confidence"] == 0.95

    def test_user_confirmed_mapping_locked(self, db):
        """Once a user confirms a mapping, auto-updates can't downgrade it."""
        db.save_mapping("tally", "Vch No.", "voucher_no",
                        confidence=1.0, confirmed_by_user=True)
        # Try to overwrite with lower confidence (auto-detected)
        db.save_mapping("tally", "Vch No.", "reference", confidence=0.6)
        result = db.get_mapping("tally", "Vch No.")
        assert result["mapped_to"] == "voucher_no"  # unchanged
        assert result["confidence"] == 1.0

    def test_no_mapping_returns_none(self, db):
        result = db.get_mapping("unknown_software", "random_column")
        assert result is None

    def test_mapping_update_increments_count(self, db):
        db.save_mapping("excel", "Date", "transaction_date", confidence=0.8)
        db.save_mapping("excel", "Date", "transaction_date", confidence=0.9)
        with db.connection() as conn:
            result = conn.execute(
                "SELECT times_seen FROM bronze_schema_mappings "
                "WHERE source_software = 'excel' AND original_column = 'Date'"
            ).fetchone()
        assert result[0] == 2


# ── Utilities ────────────────────────────────────────────────────────────────

class TestUtilities:
    def test_file_hash_deterministic(self, tmp_path):
        """Same file content → same hash every time."""
        f = tmp_path / "test.txt"
        f.write_text("Hello Neural Ledger")
        hash1 = DatabaseManager.file_hash(str(f))
        hash2 = DatabaseManager.file_hash(str(f))
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex length

    def test_different_files_different_hashes(self, tmp_path):
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f1.write_text("Content A")
        f2.write_text("Content B")
        assert DatabaseManager.file_hash(str(f1)) != DatabaseManager.file_hash(str(f2))

    def test_duplicate_file_detection(self, db, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b,c\n1,2,3")
        file_hash = DatabaseManager.file_hash(str(f))

        assert db.is_duplicate_file(file_hash) is False

        with db.connection() as conn:
            conn.execute("""
                INSERT INTO bronze_transactions
                    (source_type, source_software, source_file,
                     source_file_hash, raw_content, ingestion_batch_id)
                VALUES ('csv', 'manual_excel', 'test.csv', ?, '{"a":1}', 'b-1')
            """, [file_hash])

        assert db.is_duplicate_file(file_hash) is True


# ── Phase 2 Contract ─────────────────────────────────────────────────────────

class TestPhase2Contract:
    def test_phase2_reads_gold_only(self, db):
        """Phase 2 should be able to read from Gold layer."""
        with db.connection() as conn:
            conn.execute("""
                INSERT INTO gold_transactions
                    (silver_id, bronze_id, transaction_date, year_month,
                     embedding_text, quality_score, category, vendor)
                VALUES ('s-p2', 'b-p2', '2024-01-15', '2024-01',
                        'On 15 Jan 2024, PKR 5,000 was paid to Shell — Fuel',
                        0.85, 'Fuel', 'Shell')
            """)

        with db.read_connection() as conn:
            result = conn.execute(
                "SELECT embedding_text, category, vendor FROM gold_transactions"
            ).fetchone()

        assert "Shell" in result[0]
        assert result[1] == "Fuel"
        assert result[2] == "Shell"

    def test_full_lineage_chain(self, db):
        """Gold → Silver → Bronze lineage must be traceable."""
        with db.connection() as conn:
            # Bronze
            conn.execute("""
                INSERT INTO bronze_transactions
                    (bronze_id, source_type, source_software, source_file,
                     source_file_hash, raw_content, ingestion_batch_id)
                VALUES ('b-lineage', 'csv', 'tally', 'daybook.csv',
                        'lineagehash', '{"Dr":"5000"}', 'batch-lineage')
            """)
            # Silver
            conn.execute("""
                INSERT INTO silver_transactions
                    (silver_id, bronze_id, transaction_date, year_month,
                     amount_debit, amount_credit)
                VALUES ('s-lineage', 'b-lineage', '2024-01-15', '2024-01', 5000, 0)
            """)
            # Gold
            conn.execute("""
                INSERT INTO gold_transactions
                    (silver_id, bronze_id, transaction_date, year_month,
                     embedding_text, quality_score)
                VALUES ('s-lineage', 'b-lineage', '2024-01-15', '2024-01',
                        'Lineage test', 0.9)
            """)

        # Trace from Gold → Silver → Bronze
        with db.read_connection() as conn:
            gold = conn.execute(
                "SELECT silver_id, bronze_id FROM gold_transactions WHERE bronze_id = 'b-lineage'"
            ).fetchone()
            assert gold[0] == "s-lineage"
            assert gold[1] == "b-lineage"

            silver = conn.execute(
                "SELECT bronze_id FROM silver_transactions WHERE silver_id = ?"
                , [gold[0]]
            ).fetchone()
            assert silver[0] == "b-lineage"

            bronze = conn.execute(
                "SELECT raw_content FROM bronze_transactions WHERE bronze_id = ?"
                , [silver[0]]
            ).fetchone()
            assert bronze[0] is not None
