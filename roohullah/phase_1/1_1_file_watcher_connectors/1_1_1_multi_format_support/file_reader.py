"""
1.1.1 — Multi-Format File Reader (Standalone Module)
-----------------------------------------------------
Reads financial data files (CSV, XLSX) into a pandas DataFrame.
This is a STANDALONE module — no database, no API, no FastAPI needed.
You can test it by itself:

    python file_reader.py sample.csv

Dependencies:
    pip install pandas openpyxl chardet

What this does:
    1. Takes a file (bytes or path)
    2. Detects the format (CSV vs Excel)
    3. Tries multiple encodings (UTF-8, Latin-1, CP1252)
    4. Returns a raw DataFrame — no normalization, no cleaning

Future:
    - PDF bank statement OCR (Tesseract + pdf2image)
    - JSON / API ingestion
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional

import pandas as pd


# ── Exceptions ────────────────────────────────────────────────────────────────
class UnsupportedFormatError(Exception):
    """Raised when the file extension is not CSV or Excel."""
    pass


class ReadError(Exception):
    """Raised when the file cannot be decoded or read."""
    pass


# ── Public API ────────────────────────────────────────────────────────────────
def read_file(
    *,
    content: Optional[bytes] = None,
    filepath: Optional[str] = None,
) -> pd.DataFrame:
    """
    Read a financial data file into a raw DataFrame.

    Provide EITHER content (bytes) OR filepath (path string), not both.
    Returns the raw DataFrame — columns are NOT renamed or normalized.

    Args:
        content:  raw file bytes (e.g. from an upload)
        filepath: path to a local file

    Returns:
        pd.DataFrame with whatever columns the file has

    Raises:
        UnsupportedFormatError: if the file extension is not .csv/.xlsx/.xls
        ReadError: if the file cannot be decoded
    """
    if filepath and not content:
        path = Path(filepath)
        if not path.exists():
            raise ReadError(f"File not found: {filepath}")
        content = path.read_bytes()
        filename = path.name
    elif content and not filepath:
        filename = "uploaded_file"
    elif content and filepath:
        filename = Path(filepath).name
    else:
        raise ReadError("Provide either content (bytes) or filepath")

    ext = _get_extension(filename if filepath else "file.csv")
    if filepath:
        ext = _get_extension(filename)

    if ext == ".csv":
        return _read_csv(content)
    elif ext in (".xlsx", ".xls", ".xlsm"):
        return _read_excel(content)
    else:
        raise UnsupportedFormatError(
            f"Unsupported file format: '{ext}'. "
            f"Supported: .csv, .xlsx, .xls, .xlsm"
        )


def read_file_from_path(filepath: str) -> pd.DataFrame:
    """Convenience: read a file by its path."""
    return read_file(filepath=filepath)


def read_file_from_bytes(content: bytes, filename: str) -> pd.DataFrame:
    """Convenience: read uploaded file bytes with a filename hint."""
    ext = _get_extension(filename)
    if ext == ".csv":
        return _read_csv(content)
    elif ext in (".xlsx", ".xls", ".xlsm"):
        return _read_excel(content)
    else:
        raise UnsupportedFormatError(
            f"Unsupported: '{filename}'. Use .csv or .xlsx"
        )


# ── Internal: CSV reader with encoding fallback ──────────────────────────────
def _read_csv(content: bytes) -> pd.DataFrame:
    """
    Try multiple encodings to read a CSV.

    Pakistani SMEs often save files in different encodings:
      - UTF-8:    modern default
      - UTF-8-sig: Excel on Windows adds a BOM (byte order mark)
      - Latin-1:   old-school, covers Western European characters
      - CP1252:    Windows-specific encoding

    We try each one. First success wins.
    """
    encodings = ("utf-8", "utf-8-sig", "latin-1", "cp1252")
    for enc in encodings:
        try:
            return pd.read_csv(io.BytesIO(content), encoding=enc)
        except UnicodeDecodeError:
            continue

    raise ReadError(
        "Unable to decode CSV file. "
        "Try saving it as UTF-8 in Excel (Save As > CSV UTF-8)."
    )


# ── Internal: Excel reader ───────────────────────────────────────────────────
def _read_excel(content: bytes) -> pd.DataFrame:
    """Read first sheet of an Excel file using openpyxl engine."""
    return pd.read_excel(io.BytesIO(content), engine="openpyxl")


# ── Internal: extension helper ───────────────────────────────────────────────
def _get_extension(filename: str) -> str:
    """Get lowercased file extension."""
    return Path(filename).suffix.lower()


# ── CLI entry point (for standalone testing) ──────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python file_reader.py <path_to_csv_or_xlsx>")
        sys.exit(1)

    filepath = sys.argv[1]
    print(f"Reading: {filepath}")

    df = read_file_from_path(filepath)
    print(f"\nShape: {df.shape[0]} rows x {df.shape[1]} columns")
    print(f"Columns: {list(df.columns)}")
    print(f"\nFirst 5 rows:")
    print(df.head().to_string())
