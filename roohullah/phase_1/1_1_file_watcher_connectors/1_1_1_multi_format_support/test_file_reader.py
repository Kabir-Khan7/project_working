"""
Tests for 1.1.1 Multi-Format File Reader
-----------------------------------------
Run: python -m pytest test_file_reader.py -v
No database needed — these are pure unit tests.
"""

import io
import pandas as pd
import pytest
from file_reader import (
    read_file_from_bytes,
    read_file_from_path,
    ReadError,
    UnsupportedFormatError,
)


# ── Helper: create sample files in memory ─────────────────────────────────────
def make_csv_bytes() -> bytes:
    df = pd.DataFrame({
        "Date": ["2026-01-15", "2026-01-16"],
        "Description": ["Office Rent", "Salary"],
        "Amount": [50000, 200000],
    })
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def make_xlsx_bytes() -> bytes:
    df = pd.DataFrame({
        "txn_date": ["2026-02-01", "2026-02-05"],
        "narration": ["Internet bill", "Cash sale"],
        "amount": [-3500, 12000],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


# ── CSV Tests ─────────────────────────────────────────────────────────────────
def test_read_csv_returns_dataframe():
    df = read_file_from_bytes(make_csv_bytes(), "transactions.csv")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2


def test_csv_has_correct_columns():
    df = read_file_from_bytes(make_csv_bytes(), "data.csv")
    assert "Date" in df.columns
    assert "Description" in df.columns
    assert "Amount" in df.columns


# ── Excel Tests ───────────────────────────────────────────────────────────────
def test_read_xlsx_returns_dataframe():
    df = read_file_from_bytes(make_xlsx_bytes(), "ledger.xlsx")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2


def test_xlsx_has_correct_columns():
    df = read_file_from_bytes(make_xlsx_bytes(), "report.xlsx")
    assert "txn_date" in df.columns
    assert "narration" in df.columns


# ── Error handling ────────────────────────────────────────────────────────────
def test_unsupported_format_raises():
    with pytest.raises(UnsupportedFormatError):
        read_file_from_bytes(b"some data", "report.txt")


def test_unsupported_pdf_raises():
    """PDF OCR is not yet implemented — should raise UnsupportedFormatError."""
    with pytest.raises(UnsupportedFormatError):
        read_file_from_bytes(b"%PDF-1.4", "statement.pdf")


def test_nonexistent_file_raises():
    with pytest.raises(ReadError):
        read_file_from_path("/nonexistent/path/file.csv")


# ── Edge cases ────────────────────────────────────────────────────────────────
def test_empty_csv():
    """A CSV with only headers should return an empty DataFrame."""
    content = b"Date,Description,Amount\n"
    df = read_file_from_bytes(content, "empty.csv")
    assert len(df) == 0
    assert list(df.columns) == ["Date", "Description", "Amount"]
