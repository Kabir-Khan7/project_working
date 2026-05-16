"""
1.2.3 — Security Gates (Standalone Module)
--------------------------------------------
Seven security gates protecting the ingestion pipeline.

These gates run BEFORE any data enters the normalization pipeline.
They neutralize attacks, sanitize inputs, and prevent schema confusion.

Gate 1: File size check         — blocks DoS via huge files
Gate 2: Row count check         — prevents memory exhaustion
Gate 3: Formula neutralization  — stops Excel/CSV injection attacks
Gate 4: Reserved name protection— prevents schema confusion
Gate 5: Unicode normalization   — blocks encoding bypass attacks
Gate 6: LLM output validation   — validates AI mapping responses
Gate 7: Amount parsing & sanitization — safe type coercion

Dependencies:
    pip install unicodedata2 (optional, stdlib unicodedata works)

Usage:
    from security_gates import SecurityGatekeeper

    gatekeeper = SecurityGatekeeper()
    result = gatekeeper.run_all_gates(rows, headers, file_size_bytes=24576)
    # result.passed = True/False
    # result.warnings = ["Gate 3: Formula removed from cell B5"]
    # result.sanitized_rows = [...]  (cleaned data)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


# ── Configuration ────────────────────────────────────────────────────────────

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_ROW_COUNT = 500_000
MAX_CELL_LENGTH = 10_000

# Neural Ledger internal fields that user data must never overwrite
RESERVED_COLUMN_NAMES = frozenset({
    "bronze_id", "silver_id", "transaction_id", "gold_version",
    "quality_score", "embedding_text", "qdrant_indexed",
    "processing_status", "ingestion_batch_id", "source_file_hash",
    "pii_masked", "pii_types_found", "normalised_at", "promoted_at",
    "pipeline_audit_log", "is_duplicate", "duplicate_of",
})

# Patterns that indicate Excel/CSV formula injection
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "|")
FORMULA_DANGEROUS_PATTERNS = [
    re.compile(r"=\s*(HYPERLINK|IMPORTXML|IMPORTDATA|IMPORTRANGE|IMAGE)", re.IGNORECASE),
    re.compile(r"=\s*CMD\s*\(", re.IGNORECASE),
    re.compile(r"=\s*EXEC\s*\(", re.IGNORECASE),
    re.compile(r"\|.*\|", re.IGNORECASE),  # pipe-based DDE
]


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class GateResult:
    """Result of running all security gates."""
    passed: bool = True
    blocked: bool = False
    block_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    sanitized_rows: list[dict[str, Any]] = field(default_factory=list)
    sanitized_headers: list[str] = field(default_factory=list)
    renamed_columns: dict[str, str] = field(default_factory=dict)


# ── Security Gatekeeper ──────────────────────────────────────────────────────

class SecurityGatekeeper:
    """
    Runs 7 security gates on ingestion data.

    Usage:
        gatekeeper = SecurityGatekeeper()
        result = gatekeeper.run_all_gates(rows, headers, file_size_bytes=24576)
    """

    def __init__(
        self,
        max_file_size: int = MAX_FILE_SIZE_BYTES,
        max_row_count: int = MAX_ROW_COUNT,
    ):
        self.max_file_size = max_file_size
        self.max_row_count = max_row_count

    def run_all_gates(
        self,
        rows: list[dict[str, Any]],
        headers: list[str],
        file_size_bytes: int = 0,
    ) -> GateResult:
        """
        Run all 7 security gates sequentially.
        Gates 1-2 can BLOCK (reject file entirely).
        Gates 3-7 SANITIZE (clean and continue).
        """
        result = GateResult()

        # Gate 1: File size check
        if not self._gate_1_file_size(file_size_bytes, result):
            return result

        # Gate 2: Row count check
        if not self._gate_2_row_count(rows, result):
            return result

        # Gate 4: Reserved name protection (before formula check)
        headers = self._gate_4_reserved_names(headers, result)

        # Gate 5: Unicode normalization on headers
        headers = self._gate_5_unicode_normalize(headers, result)

        result.sanitized_headers = headers

        # Gate 3: Formula neutralization (on cell values)
        sanitized_rows = self._gate_3_formula_neutralize(rows, result)

        # Gate 7: Amount parsing & sanitization
        sanitized_rows = self._gate_7_amount_sanitize(sanitized_rows, result)

        result.sanitized_rows = sanitized_rows
        return result

    # ── Gate 1: File Size ────────────────────────────────────────────────────

    def _gate_1_file_size(self, file_size_bytes: int, result: GateResult) -> bool:
        """Block files exceeding the size limit (DoS prevention)."""
        if file_size_bytes > self.max_file_size:
            result.passed = False
            result.blocked = True
            result.block_reason = (
                f"Gate 1 BLOCKED: File size {file_size_bytes:,} bytes exceeds "
                f"limit of {self.max_file_size:,} bytes"
            )
            return False
        return True

    # ── Gate 2: Row Count ────────────────────────────────────────────────────

    def _gate_2_row_count(self, rows: list, result: GateResult) -> bool:
        """Block files with too many rows (memory exhaustion prevention)."""
        if len(rows) > self.max_row_count:
            result.passed = False
            result.blocked = True
            result.block_reason = (
                f"Gate 2 BLOCKED: Row count {len(rows):,} exceeds "
                f"limit of {self.max_row_count:,}"
            )
            return False
        return True

    # ── Gate 3: Formula Neutralization ───────────────────────────────────────

    def _gate_3_formula_neutralize(
        self, rows: list[dict[str, Any]], result: GateResult
    ) -> list[dict[str, Any]]:
        """
        Neutralize formula injection attacks in cell values.

        Malicious cells like =HYPERLINK("evil.com") are stored as
        FORMULA_REMOVED:=HYPERLINK("evil.com") — never executed.
        """
        sanitized = []
        for row_idx, row in enumerate(rows):
            clean_row = {}
            for key, value in row.items():
                if isinstance(value, str):
                    cleaned = self._neutralize_formula(value)
                    if cleaned != value:
                        result.warnings.append(
                            f"Gate 3: Formula neutralized in row {row_idx + 1}, "
                            f"column '{key}'"
                        )
                    clean_row[key] = cleaned
                else:
                    clean_row[key] = value
            sanitized.append(clean_row)
        return sanitized

    def _neutralize_formula(self, value: str) -> str:
        """Remove dangerous formula prefixes and patterns."""
        if not value:
            return value

        # Check for dangerous formula patterns
        for pattern in FORMULA_DANGEROUS_PATTERNS:
            if pattern.search(value):
                return f"FORMULA_REMOVED:{value}"

        # Check for simple formula prefix (but allow negative numbers)
        if value.startswith(FORMULA_PREFIXES):
            # Allow negative numbers like "-5000"
            if value.startswith("-") and self._looks_like_number(value):
                return value
            # Allow positive numbers like "+5000"
            if value.startswith("+") and self._looks_like_number(value):
                return value
            # Block everything else starting with formula chars
            if value.startswith(("=", "@", "\t", "\r")):
                return f"FORMULA_REMOVED:{value}"
            # For + and - that aren't numbers, also block
            if value.startswith(("+", "-")) and not self._looks_like_number(value):
                return f"FORMULA_REMOVED:{value}"

        return value

    @staticmethod
    def _looks_like_number(value: str) -> bool:
        """Check if a string looks like a numeric value."""
        cleaned = value.replace(",", "").replace(" ", "").strip()
        try:
            float(cleaned)
            return True
        except (ValueError, TypeError):
            return False

    # ── Gate 4: Reserved Name Protection ─────────────────────────────────────

    def _gate_4_reserved_names(
        self, headers: list[str], result: GateResult
    ) -> list[str]:
        """
        Rename any column that conflicts with Neural Ledger internal fields.

        If an incoming file has a column called 'quality_score', it gets
        renamed to 'raw_quality_score' to prevent schema confusion.
        """
        cleaned = []
        for header in headers:
            lower = header.lower().strip()
            if lower in RESERVED_COLUMN_NAMES:
                new_name = f"raw_{header}"
                result.renamed_columns[header] = new_name
                result.warnings.append(
                    f"Gate 4: Reserved column '{header}' renamed to '{new_name}'"
                )
                cleaned.append(new_name)
            else:
                cleaned.append(header)
        return cleaned

    # ── Gate 5: Unicode Normalization ────────────────────────────────────────

    def _gate_5_unicode_normalize(
        self, headers: list[str], result: GateResult
    ) -> list[str]:
        """
        Normalize Unicode in headers to prevent homoglyph attacks.

        E.g., Cyrillic 'а' (U+0430) looks identical to Latin 'a' (U+0061).
        NFC normalization ensures consistent representation.
        """
        normalized = []
        for header in headers:
            nfc = unicodedata.normalize("NFC", header)
            if nfc != header:
                result.warnings.append(
                    f"Gate 5: Unicode normalized '{header}' → '{nfc}'"
                )
            normalized.append(nfc)
        return normalized

    # ── Gate 6: LLM Output Validation ────────────────────────────────────────

    @staticmethod
    def validate_llm_mapping(
        llm_response: dict[str, str],
        valid_targets: set[str],
    ) -> tuple[dict[str, str], list[str]]:
        """
        Validate that LLM-suggested column mappings are safe.

        Args:
            llm_response:  {"original_col": "mapped_col", ...} from LLM
            valid_targets: set of valid Neural Ledger field names

        Returns:
            (validated_mapping, warnings)
        """
        validated = {}
        warnings = []

        for source, target in llm_response.items():
            # Reject if target is not a valid field
            if target.lower() not in valid_targets:
                warnings.append(
                    f"Gate 6: LLM suggested invalid target '{target}' "
                    f"for '{source}' — rejected"
                )
                continue

            # Reject if target is a reserved internal field
            if target.lower() in RESERVED_COLUMN_NAMES:
                warnings.append(
                    f"Gate 6: LLM tried to map to reserved field '{target}' "
                    f"— rejected"
                )
                continue

            # Reject suspiciously long mappings (possible injection)
            if len(target) > 50:
                warnings.append(
                    f"Gate 6: LLM target '{target[:30]}...' too long — rejected"
                )
                continue

            validated[source] = target

        return validated, warnings

    # ── Gate 7: Amount Parsing & Sanitization ────────────────────────────────

    def _gate_7_amount_sanitize(
        self, rows: list[dict[str, Any]], result: GateResult
    ) -> list[dict[str, Any]]:
        """
        Sanitize and truncate overly long cell values.
        Prevents memory issues from maliciously long strings.
        """
        sanitized = []
        for row in rows:
            clean_row = {}
            for key, value in row.items():
                if isinstance(value, str) and len(value) > MAX_CELL_LENGTH:
                    result.warnings.append(
                        f"Gate 7: Cell in '{key}' truncated "
                        f"({len(value)} → {MAX_CELL_LENGTH} chars)"
                    )
                    clean_row[key] = value[:MAX_CELL_LENGTH]
                else:
                    clean_row[key] = value
            sanitized.append(clean_row)
        return sanitized


# ── Standalone Amount Parser ─────────────────────────────────────────────────

def parse_amount(value: Any) -> float | None:
    """
    Parse Pakistani-style amount strings into float.

    Handles:
        "PKR 45,000"     → 45000.0
        "Rs. 12,500.50"  → 12500.5
        "(5,000)"        → -5000.0  (accountant negative convention)
        "5000"           → 5000.0
        "N/A"            → None
        ""               → None
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text or text.lower() in ("n/a", "nil", "-", "—", "null", "none"):
        return None

    # Detect negative (parentheses convention)
    is_negative = False
    if text.startswith("(") and text.endswith(")"):
        is_negative = True
        text = text[1:-1]

    # Remove currency prefixes
    for prefix in ("PKR", "Rs.", "Rs", "USD", "$", "EUR", "€", "GBP", "£"):
        if text.upper().startswith(prefix.upper()):
            text = text[len(prefix):].strip()
            break

    # Remove thousands separators and spaces
    text = text.replace(",", "").replace(" ", "")

    # Handle trailing CR/DR markers
    text = re.sub(r"\s*(DR|CR|Dr|Cr)\.?\s*$", "", text)

    try:
        amount = float(text)
        return -amount if is_negative else amount
    except (ValueError, TypeError):
        return None


# ── CLI Demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    gatekeeper = SecurityGatekeeper()

    # Test data with security issues
    headers = ["Date", "Amount", "quality_score", "Description"]
    rows = [
        {"Date": "15/01/2024", "Amount": "5000", "quality_score": "0.9",
         "Description": "Normal payment"},
        {"Date": "16/01/2024", "Amount": "PKR 12,500",  "quality_score": "0.8",
         "Description": '=HYPERLINK("http://evil.com","Click here")'},
        {"Date": "17/01/2024", "Amount": "(3,000)", "quality_score": "0.7",
         "Description": "Refund"},
    ]

    result = gatekeeper.run_all_gates(rows, headers, file_size_bytes=1024)

    print("Security Gate Results:")
    print(f"  Passed: {result.passed}")
    print(f"  Blocked: {result.blocked}")
    print(f"  Warnings: {len(result.warnings)}")
    for w in result.warnings:
        print(f"    - {w}")
    print(f"  Renamed columns: {result.renamed_columns}")
    print(f"\nAmount parsing examples:")
    for test in ["PKR 45,000", "Rs. 12,500.50", "(5,000)", "N/A", "5000"]:
        print(f"  '{test}' → {parse_amount(test)}")
