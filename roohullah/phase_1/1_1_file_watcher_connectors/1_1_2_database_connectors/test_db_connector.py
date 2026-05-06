"""
Tests for 1.1.2 Database Connectors
-------------------------------------
Uses an in-memory SQLite database — no external DB server needed.
Run: python -m pytest test_db_connector.py -v
"""

import sqlite3
import tempfile
import os

import pandas as pd
import pytest
from db_connector import (
    DatabaseConnector,
    ConnectionFailedError,
    TableNotFoundError,
    ConnectorError,
)


# ── Fixture: create a temp SQLite DB with sample data ─────────────────────────
@pytest.fixture
def sample_db():
    """Creates a temp SQLite DB with a 'transactions' table."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            date TEXT,
            description TEXT,
            amount REAL,
            type TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO transactions (date, description, amount, type) VALUES (?, ?, ?, ?)",
        [
            ("2026-01-15", "Office Rent", 50000, "debit"),
            ("2026-01-16", "Sale to ABC Co", 80000, "credit"),
            ("2026-01-17", "Internet Bill", 3500, "debit"),
        ],
    )
    conn.commit()
    conn.close()

    yield path

    # Cleanup
    os.unlink(path)


# ── Connection Tests ──────────────────────────────────────────────────────────
def test_sqlite_connects(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        assert conn.db_type == "sqlite"


def test_sqlite_nonexistent_file():
    with pytest.raises(ConnectionFailedError):
        DatabaseConnector.sqlite("/fake/path/nope.db")


# ── Table Listing ─────────────────────────────────────────────────────────────
def test_list_tables(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        tables = conn.list_tables()
        assert "transactions" in tables


# ── Read Table ────────────────────────────────────────────────────────────────
def test_read_table(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        df = conn.read_table("transactions")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "description" in df.columns


def test_read_table_with_limit(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        df = conn.read_table("transactions", limit=2)
        assert len(df) == 2


def test_read_nonexistent_table(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        with pytest.raises(TableNotFoundError):
            conn.read_table("does_not_exist")


# ── Custom Query ──────────────────────────────────────────────────────────────
def test_read_query(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        df = conn.read_query("SELECT * FROM transactions WHERE type = 'debit'")
        assert len(df) == 2
        assert all(df["type"] == "debit")


def test_read_query_blocks_insert(sample_db):
    """INSERT statements must be blocked (read-only)."""
    with DatabaseConnector.sqlite(sample_db) as conn:
        with pytest.raises(ConnectorError, match="Only SELECT"):
            conn.read_query("INSERT INTO transactions VALUES (99, '2026', 'hack', 0, 'x')")


def test_read_query_blocks_delete(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        with pytest.raises(ConnectorError, match="Only SELECT"):
            conn.read_query("DELETE FROM transactions")


def test_read_query_blocks_drop(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        with pytest.raises(ConnectorError, match="Only SELECT"):
            conn.read_query("DROP TABLE transactions")


# ── Table Info ────────────────────────────────────────────────────────────────
def test_get_table_info(sample_db):
    with DatabaseConnector.sqlite(sample_db) as conn:
        info = conn.get_table_info("transactions")
        names = [col["name"] for col in info]
        assert "id" in names
        assert "description" in names
        assert "amount" in names
