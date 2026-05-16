"""
1.0.1 — Medallion Architecture Database Manager (Standalone Module)
--------------------------------------------------------------------
DuckDB-based local database with Bronze → Silver → Gold layers.

DuckDB is an embedded analytical database — zero install, no server,
runs inside the Python process. Think of it as "SQLite for analytics."

Why DuckDB over PostgreSQL for local storage?
    - Zero configuration (no Docker, no server)
    - Embedded (runs inside your app process)
    - 10-100x faster than SQLite for analytical queries
    - Works on 2GB RAM machines
    - Single file on disk (storage/neural_ledger.db)

Usage:
    from db_manager import DatabaseManager

    db = DatabaseManager()
    db.initialise()

    # Write to Bronze
    with db.connection() as conn:
        conn.execute("INSERT INTO bronze_transactions ...")

    # Read from Gold (Phase 2)
    with db.read_connection() as conn:
        df = conn.execute("SELECT * FROM gold_transactions").fetchdf()

    # Audit logging
    db.log_operation("bronze_insert", "bronze", "success", rows_affected=50)

    # Health check
    stats = db.get_table_stats()
    # {"bronze_transactions": 0, "silver_transactions": 0, ...}

Dependencies:
    pip install duckdb python-dotenv
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import duckdb

# ── Configuration ────────────────────────────────────────────────────────────

# Defaults — can be overridden via environment variables or .env file
DEFAULT_DB_PATH = "storage/neural_ledger.db"
DEFAULT_MEMORY_LIMIT = "512MB"
DEFAULT_THREADS = 4
DEFAULT_QUALITY_GATE = 0.7


class DatabaseManager:
    """
    Manages the DuckDB Medallion Architecture database.

    This is the foundation of Neural Ledger's local data layer.
    All financial data flows through Bronze → Silver → Gold.

    Attributes:
        db_path:        Path to the DuckDB file on disk
        memory_limit:   Max RAM for DuckDB (default: 512MB)
        threads:        Parallel query threads (default: 4)
        quality_gate:   Minimum quality_score for Gold entry (default: 0.7)
    """

    def __init__(
        self,
        db_path: str | None = None,
        memory_limit: str | None = None,
        threads: int | None = None,
        quality_gate: float | None = None,
    ):
        self.db_path = db_path or os.getenv("DB_PATH", DEFAULT_DB_PATH)
        self.memory_limit = memory_limit or os.getenv("DB_MEMORY_LIMIT", DEFAULT_MEMORY_LIMIT)
        self.threads = threads or int(os.getenv("DB_THREADS", str(DEFAULT_THREADS)))
        self.quality_gate = quality_gate or float(
            os.getenv("QUALITY_GATE_MIN", str(DEFAULT_QUALITY_GATE))
        )
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._initialised = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def initialise(self) -> dict[str, int]:
        """
        Create all tables if they don't exist. Safe to call on every startup.
        Uses CREATE TABLE IF NOT EXISTS — never destroys existing data.

        Returns:
            dict of table_name → row_count
        """
        # Ensure storage directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        # Connect and configure
        self._conn = duckdb.connect(self.db_path)
        self._conn.execute(f"SET memory_limit = '{self.memory_limit}'")
        self._conn.execute(f"SET threads = {self.threads}")

        # Run schema SQL
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")

        # Strip comment lines first, then split by semicolon
        lines = [
            line for line in schema_sql.splitlines()
            if not line.strip().startswith("--")
        ]
        clean_sql = "\n".join(lines)

        for statement in clean_sql.split(";"):
            statement = statement.strip()
            if statement:
                self._conn.execute(statement)

        self._initialised = True
        return self.get_table_stats()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._initialised = False

    # ── Connection Context Managers ──────────────────────────────────────────

    @contextmanager
    def connection(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """
        Read-write connection for Phase 1 pipeline operations.

        Usage:
            with db.connection() as conn:
                conn.execute("INSERT INTO bronze_transactions ...")
        """
        if not self._initialised or not self._conn:
            raise RuntimeError("Database not initialised. Call db.initialise() first.")
        yield self._conn

    @contextmanager
    def read_connection(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """
        Read-only connection for Phase 2 / reporting.

        Note: DuckDB doesn't support concurrent read-only connections to the
        same file. Read-only contract is enforced at application layer.

        Usage:
            with db.read_connection() as conn:
                df = conn.execute("SELECT * FROM gold_transactions").fetchdf()
        """
        if not self._initialised or not self._conn:
            raise RuntimeError("Database not initialised. Call db.initialise() first.")
        # Application-layer read-only: we yield the same connection
        # but the caller is expected to only SELECT from it.
        yield self._conn

    # ── Audit Logging ────────────────────────────────────────────────────────

    def log_operation(
        self,
        operation: str,
        source_layer: str,
        status: str,
        *,
        batch_id: str | None = None,
        rows_affected: int = 0,
        error_detail: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """
        Write an entry to the pipeline_audit_log.

        Every Bronze insert, Silver normalisation, Gold promotion —
        all logged here. This is the accountability layer.

        Args:
            operation:      What happened (bronze_insert, silver_normalise, etc.)
            source_layer:   Which layer (bronze, silver, gold)
            status:         success, partial, or failed
            batch_id:       Optional batch grouping
            rows_affected:  How many rows were touched
            error_detail:   Error message if failed
            duration_ms:    How long the operation took
        """
        if not self._conn:
            return  # Silently skip if DB not ready (non-fatal)

        try:
            self._conn.execute(
                """
                INSERT INTO pipeline_audit_log
                    (operation, source_layer, batch_id, status,
                     rows_affected, error_detail, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [operation, source_layer, batch_id, status,
                 rows_affected, error_detail, duration_ms],
            )
        except Exception:
            pass  # Audit logging must never crash the pipeline

    # ── Health & Stats ───────────────────────────────────────────────────────

    def get_table_stats(self) -> dict[str, int]:
        """
        Return row counts for all Medallion tables.

        Returns:
            {"bronze_transactions": 0, "silver_transactions": 0, ...}
        """
        if not self._conn:
            return {}

        tables = [
            "bronze_transactions",
            "bronze_schema_mappings",
            "silver_transactions",
            "silver_quarantine",
            "gold_transactions",
            "gold_period_summaries",
            "pipeline_audit_log",
        ]
        stats = {}
        for table in tables:
            try:
                result = self._conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()
                stats[table] = result[0] if result else 0
            except Exception:
                stats[table] = 0
        return stats

    def is_healthy(self) -> bool:
        """Quick health check — can we query the database?"""
        if not self._conn:
            return False
        try:
            self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    # ── Utility ──────────────────────────────────────────────────────────────

    @staticmethod
    def file_hash(file_path: str) -> str:
        """
        Compute SHA-256 hash of a file.
        Used for duplicate detection — same hash = same file.
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def is_duplicate_file(self, file_hash: str) -> bool:
        """Check if a file with this hash has already been ingested."""
        if not self._conn:
            return False
        result = self._conn.execute(
            "SELECT COUNT(*) FROM bronze_transactions WHERE source_file_hash = ?",
            [file_hash],
        ).fetchone()
        return (result[0] if result else 0) > 0

    # ── Schema Mapping Memory ────────────────────────────────────────────────

    def get_mapping(self, source_software: str, original_column: str) -> dict | None:
        """
        Look up a previously learned column mapping.

        Returns:
            {"mapped_to": "transaction_date", "confidence": 0.95, "confirmed": True}
            or None if no mapping exists.
        """
        if not self._conn:
            return None

        result = self._conn.execute(
            """
            SELECT mapped_to, confidence, confirmed_by_user
            FROM bronze_schema_mappings
            WHERE source_software = ? AND original_column = ?
            """,
            [source_software, original_column],
        ).fetchone()

        if result:
            return {
                "mapped_to": result[0],
                "confidence": result[1],
                "confirmed": result[2],
            }
        return None

    def save_mapping(
        self,
        source_software: str,
        original_column: str,
        mapped_to: str,
        confidence: float = 0.5,
        confirmed_by_user: bool = False,
    ) -> None:
        """
        Save or update a column mapping. If the user confirms, lock it at 1.0.
        """
        if not self._conn:
            return

        existing = self.get_mapping(source_software, original_column)
        if existing:
            # Don't downgrade user-confirmed mappings
            if existing["confirmed"] and not confirmed_by_user:
                return
            self._conn.execute(
                """
                UPDATE bronze_schema_mappings
                SET mapped_to = ?, confidence = ?, confirmed_by_user = ?,
                    times_seen = times_seen + 1, updated_at = current_timestamp
                WHERE source_software = ? AND original_column = ?
                """,
                [mapped_to, confidence, confirmed_by_user,
                 source_software, original_column],
            )
        else:
            self._conn.execute(
                """
                INSERT INTO bronze_schema_mappings
                    (source_software, original_column, mapped_to, confidence, confirmed_by_user)
                VALUES (?, ?, ?, ?, ?)
                """,
                [source_software, original_column, mapped_to,
                 confidence, confirmed_by_user],
            )

    # ── Repr ─────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "initialised" if self._initialised else "not initialised"
        return f"DatabaseManager(path={self.db_path!r}, {status})"


# ── Singleton for application-wide use ───────────────────────────────────────
db = DatabaseManager()


# ── CLI Demo ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    manager = DatabaseManager(db_path="storage/neural_ledger_demo.db")
    stats = manager.initialise()

    print("Database ready. Table status:")
    for table, count in stats.items():
        print(f"  {table}: {count} rows")

    print(f"\nHealthy: {manager.is_healthy()}")
    print(f"DB file: {manager.db_path}")

    manager.close()
    print("\nDone. Check your storage/ folder for the .db file.")
