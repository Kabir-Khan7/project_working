"""
1.1.4 — Accounting Software Detector (Standalone Module)
---------------------------------------------------------
Identifies what type of file was dropped and which accounting software
most likely produced it. This is critical because every software exports
data in a different column format.

Detection strategy:
    1. File extension → source_type (xlsx, csv, pdf, json)
    2. Filename patterns → source_software (tally, quickbooks, etc.)
    3. Confidence score → how certain we are

Supported software:
    - Tally / TallyPrime
    - QuickBooks Desktop / Online
    - LedgerMax
    - Xero
    - Moneypex
    - Odoo / ERPNext
    - Sage 50
    - Pakistani bank PDFs (HBL, UBL, Alfalah, Meezan, NBP)
    - Generic manual Excel

Dependencies:
    None (pure Python)

Usage:
    from software_detector import detect_file, is_supported, is_ignored

    result = detect_file("TallyPrime_Daybook_Jan2024.xlsx")
    # result = DetectionResult(
    #     source_type="xlsx",
    #     source_software="tally",
    #     confidence=0.90,
    #     is_supported=True,
    # )
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


# ── Supported extensions ─────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".pdf": "pdf",
    ".json": "json",
}

# Extensions to silently ignore (temp/lock/backup files)
IGNORED_EXTENSIONS = frozenset({
    ".tmp", ".bak", ".swp", ".lock", ".log",
    ".pyc", ".pyo", ".DS_Store",
})


# ── Software detection rules ────────────────────────────────────────────────
# Each rule: (compiled_regex, source_software, confidence)
# Order matters: first match wins. More specific patterns go first.

SOFTWARE_RULES: list[tuple[re.Pattern, str, float]] = [
    # ── Tally / TallyPrime ──
    (re.compile(r"tally\s*prime", re.IGNORECASE), "tally", 0.90),
    (re.compile(r"tally", re.IGNORECASE), "tally", 0.85),
    (re.compile(r"daybook", re.IGNORECASE), "tally", 0.75),
    (re.compile(r"vch[_\s]?type", re.IGNORECASE), "tally", 0.70),

    # ── QuickBooks ──
    (re.compile(r"quickbooks?[\s_\-]*online", re.IGNORECASE), "quickbooks_online", 0.90),
    (re.compile(r"quickbooks?[\s_\-]*desktop", re.IGNORECASE), "quickbooks_desktop", 0.90),
    (re.compile(r"quickbooks?", re.IGNORECASE), "quickbooks_desktop", 0.85),
    (re.compile(r"qb[_\s]?export", re.IGNORECASE), "quickbooks_desktop", 0.80),

    # ── LedgerMax ──
    (re.compile(r"ledgermax", re.IGNORECASE), "ledgermax", 0.95),

    # ── Xero ──
    (re.compile(r"xero", re.IGNORECASE), "xero", 0.90),

    # ── Moneypex ──
    (re.compile(r"moneypex", re.IGNORECASE), "moneypex", 0.95),

    # ── Odoo / ERPNext ──
    (re.compile(r"odoo", re.IGNORECASE), "odoo", 0.90),
    (re.compile(r"erpnext", re.IGNORECASE), "erpnext", 0.90),

    # ── Sage 50 ──
    (re.compile(r"sage\s*50", re.IGNORECASE), "sage50", 0.90),
    (re.compile(r"sage", re.IGNORECASE), "sage50", 0.75),

    # ── Pakistani Bank PDFs ──
    (re.compile(r"hbl.*statement|statement.*hbl", re.IGNORECASE), "bank_pdf_hbl", 0.90),
    (re.compile(r"habib\s*bank", re.IGNORECASE), "bank_pdf_hbl", 0.85),
    (re.compile(r"ubl.*statement|statement.*ubl", re.IGNORECASE), "bank_pdf_ubl", 0.90),
    (re.compile(r"united\s*bank", re.IGNORECASE), "bank_pdf_ubl", 0.85),
    (re.compile(r"alfalah", re.IGNORECASE), "bank_pdf_alfalah", 0.90),
    (re.compile(r"meezan", re.IGNORECASE), "bank_pdf_meezan", 0.90),
    (re.compile(r"nbp.*statement|statement.*nbp", re.IGNORECASE), "bank_pdf_nbp", 0.90),
    (re.compile(r"national\s*bank", re.IGNORECASE), "bank_pdf_nbp", 0.85),
    (re.compile(r"askari", re.IGNORECASE), "bank_pdf_askari", 0.90),
    (re.compile(r"mcb.*statement|statement.*mcb", re.IGNORECASE), "bank_pdf_mcb", 0.90),
    (re.compile(r"faysal\s*bank", re.IGNORECASE), "bank_pdf_faysal", 0.90),
    (re.compile(r"jazzcash", re.IGNORECASE), "bank_pdf_jazzcash", 0.85),
    (re.compile(r"easypaisa", re.IGNORECASE), "bank_pdf_easypaisa", 0.85),

    # ── Generic bank statement ──
    (re.compile(r"(account|bank)[\s_\-]*statement", re.IGNORECASE), "bank_pdf_generic", 0.75),

    # ── FBR / Compliance ──
    (re.compile(r"annex[_\s\-]?c", re.IGNORECASE), "fbr_annex_c", 0.90),
    (re.compile(r"fbr", re.IGNORECASE), "fbr_generic", 0.80),
    (re.compile(r"withholding[\s_\-]*tax|wht", re.IGNORECASE), "fbr_wht", 0.80),
    (re.compile(r"eobi", re.IGNORECASE), "eobi_register", 0.85),
]


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """Result of detecting a file's type and source software."""
    file_name: str
    source_type: str          # xlsx, csv, pdf, json
    source_software: str      # tally, quickbooks_desktop, manual_excel, etc.
    confidence: float         # 0.0 to 1.0
    is_supported: bool        # True if we can process this file type


# ── Public API ───────────────────────────────────────────────────────────────

def detect_file(file_path: str) -> DetectionResult:
    """
    Detect the source type and software of a file.

    Args:
        file_path: Path to the file (or just the filename)

    Returns:
        DetectionResult with source_type, source_software, confidence
    """
    file_name = os.path.basename(file_path)
    ext = os.path.splitext(file_name)[1].lower()

    # Step 1: Determine source_type from extension
    source_type = SUPPORTED_EXTENSIONS.get(ext, "unknown")
    supported = source_type != "unknown"

    # Step 2: Try to match software from filename
    source_software = "unknown"
    confidence = 0.0

    for pattern, software, conf in SOFTWARE_RULES:
        if pattern.search(file_name):
            source_software = software
            confidence = conf
            break

    # Step 3: If no software detected, use generic based on type
    if source_software == "unknown" and supported:
        if source_type in ("xlsx",):
            source_software = "manual_excel"
            confidence = 0.50
        elif source_type == "csv":
            source_software = "manual_csv"
            confidence = 0.50
        elif source_type == "pdf":
            source_software = "unknown_pdf"
            confidence = 0.30
        elif source_type == "json":
            source_software = "api_export"
            confidence = 0.40

    return DetectionResult(
        file_name=file_name,
        source_type=source_type,
        source_software=source_software,
        confidence=confidence,
        is_supported=supported,
    )


def is_supported(file_path: str) -> bool:
    """Check if a file type is supported for ingestion."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


def is_ignored(file_path: str) -> bool:
    """
    Check if a file should be silently ignored.

    Ignored files: temp files, lock files, hidden files, backup files.
    """
    file_name = os.path.basename(file_path)

    # Hidden files (start with .)
    if file_name.startswith("."):
        return True

    # Excel lock files (~$filename.xlsx)
    if file_name.startswith("~$"):
        return True

    # Ignored extensions
    ext = os.path.splitext(file_name)[1].lower()
    if ext in IGNORED_EXTENSIONS:
        return True

    return False


# ── CLI Demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_files = [
        "TallyPrime_Daybook_Jan2024.xlsx",
        "QuickBooks_General_Ledger.xlsx",
        "LedgerMax_Report_Jan.xlsx",
        "Xero_Export_Jan.csv",
        "HBL_Statement_Jan2024.pdf",
        "Meezan_Statement.pdf",
        "sales_register_jan.xlsx",
        "random_data.csv",
        "fbr_annex_c_jan.xlsx",
        "~$temp_file.xlsx",
        ".hidden_file",
        "backup.tmp",
    ]

    print("Software Detection Results:")
    print("-" * 70)
    for f in test_files:
        if is_ignored(f):
            print(f"  {f:40s} → IGNORED")
            continue
        result = detect_file(f)
        print(
            f"  {f:40s} → {result.source_software:20s} "
            f"({result.confidence:.0%}) [{result.source_type}]"
        )
