"""
1.4.1 — Ingestion Pipeline Orchestrator

Self-contained mini-pipeline demonstrating the full Phase 1 flow:
  File Detected -> Bronze Write -> Silver Normalize -> Gold Promote

Uses DuckDB directly. No imports from other phase_1 modules.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

import duckdb


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class PipelineResult:
    success: bool
    file_name: str
    batch_id: str
    bronze_rows: int = 0
    silver_rows: int = 0
    quarantined_rows: int = 0
    gold_rows: int = 0
    quality_avg: float = 0.0
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# SQL DDL
# ---------------------------------------------------------------------------
_DDL_STATEMENTS = [
    # Bronze
    """
    CREATE TABLE IF NOT EXISTS bronze_transactions (
        bronze_id VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
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
    """,
    # Silver
    """
    CREATE TABLE IF NOT EXISTS silver_transactions (
        silver_id VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
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
    )
    """,
    # Silver quarantine
    """
    CREATE TABLE IF NOT EXISTS silver_quarantine (
        quarantine_id VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
        bronze_id VARCHAR NOT NULL,
        reason VARCHAR NOT NULL,
        raw_content VARCHAR,
        error_detail VARCHAR,
        quarantined_at TIMESTAMP DEFAULT current_timestamp
    )
    """,
    # Gold
    """
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
    )
    """,
    # Audit
    """
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
    )
    """,
]


# ---------------------------------------------------------------------------
# FBR category mapping (simple keyword-based)
# ---------------------------------------------------------------------------
_FBR_CATEGORIES: dict[str, tuple[str, bool]] = {
    "rent": ("Rental Income / Expense", True),
    "salary": ("Salary / Wages", True),
    "electricity": ("Utilities", True),
    "gas": ("Utilities", True),
    "water": ("Utilities", True),
    "internet": ("Utilities", True),
    "phone": ("Utilities", True),
    "food": ("Food & Beverages", False),
    "travel": ("Travel & Conveyance", True),
    "fuel": ("Travel & Conveyance", True),
    "office": ("Office Supplies", True),
    "stationery": ("Office Supplies", True),
    "sale": ("Sales Revenue", True),
    "purchase": ("Purchases", True),
    "insurance": ("Insurance", True),
    "medical": ("Medical Expense", True),
    "tax": ("Tax Payment", False),
    "commission": ("Commission", True),
    "advertising": ("Advertising", True),
    "repair": ("Repair & Maintenance", True),
    "maintenance": ("Repair & Maintenance", True),
}


# ---------------------------------------------------------------------------
# IngestionPipeline
# ---------------------------------------------------------------------------
class IngestionPipeline:
    """Full end-to-end pipeline orchestrator: CSV -> Bronze -> Silver -> Gold."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self.conn = duckdb.connect(database=db_path)
        self._init_tables()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest_file(
        self,
        file_path: str,
        source_type: str = "csv",
        source_software: str = "manual_excel",
    ) -> PipelineResult:
        """Run the full pipeline on a single CSV file."""
        t0 = time.perf_counter_ns()
        batch_id = str(uuid4())
        file_name = os.path.basename(file_path)
        result = PipelineResult(
            success=False, file_name=file_name, batch_id=batch_id
        )

        try:
            # Step 1 — Bronze
            bronze_count = self._step_bronze(
                file_path, source_type, source_software, batch_id, result
            )
            result.bronze_rows = bronze_count
            if not result.success and result.errors:
                # duplicate file or read error — stop early
                result.duration_ms = self._elapsed_ms(t0)
                return result

            # Step 2 — Silver
            silver_count, quarantine_count, quality_avg = self._step_silver(
                batch_id, result
            )
            result.silver_rows = silver_count
            result.quarantined_rows = quarantine_count
            result.quality_avg = quality_avg

            # Step 3 — Gold
            gold_count = self._step_gold(batch_id, result)
            result.gold_rows = gold_count

            # Step 4 — Audit
            duration_ms = self._elapsed_ms(t0)
            result.duration_ms = duration_ms
            self._log_audit(
                "ingest_file",
                "pipeline",
                batch_id,
                "success",
                bronze_count,
                None,
                duration_ms,
            )

            result.success = True
            result.summary = (
                f"Ingested {file_name}: "
                f"{bronze_count} bronze -> {silver_count} silver "
                f"({quarantine_count} quarantined) -> {gold_count} gold "
                f"| avg quality {quality_avg:.2f} | {duration_ms}ms"
            )
        except Exception as exc:
            result.errors.append(str(exc))
            result.duration_ms = self._elapsed_ms(t0)
            self._log_audit(
                "ingest_file",
                "pipeline",
                batch_id,
                "error",
                0,
                str(exc),
                result.duration_ms,
            )

        return result

    def get_stats(self) -> dict:
        """Return row counts for every table."""
        tables = [
            "bronze_transactions",
            "silver_transactions",
            "silver_quarantine",
            "gold_transactions",
            "pipeline_audit_log",
        ]
        stats: dict[str, int] = {}
        for table in tables:
            row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            stats[table] = row[0] if row else 0
        return stats

    def close(self) -> None:
        """Close the DuckDB connection."""
        self.conn.close()

    # ------------------------------------------------------------------
    # Step 1 — Bronze
    # ------------------------------------------------------------------
    def _step_bronze(
        self,
        file_path: str,
        source_type: str,
        source_software: str,
        batch_id: str,
        result: PipelineResult,
    ) -> int:
        file_hash = self._file_hash(file_path)

        # Duplicate check
        existing = self.conn.execute(
            "SELECT COUNT(*) FROM bronze_transactions WHERE source_file_hash = ?",
            [file_hash],
        ).fetchone()
        if existing and existing[0] > 0:
            result.errors.append(f"Duplicate file rejected (hash {file_hash[:12]}...)")
            self._log_audit(
                "bronze_ingest",
                "bronze",
                batch_id,
                "rejected_duplicate",
                0,
                f"hash={file_hash}",
                0,
            )
            return 0

        rows = self._read_csv(file_path)
        if not rows:
            result.errors.append("CSV file is empty or could not be parsed")
            self._log_audit(
                "bronze_ingest", "bronze", batch_id, "error", 0, "empty file", 0
            )
            return 0

        headers = list(rows[0].keys())
        headers_json = json.dumps(headers, ensure_ascii=False)
        file_name = os.path.basename(file_path)

        for idx, row in enumerate(rows, start=1):
            raw_json = json.dumps(row, ensure_ascii=False)
            self.conn.execute(
                """
                INSERT INTO bronze_transactions
                    (source_type, source_software, source_file,
                     source_file_hash, source_row_number, raw_content,
                     raw_headers, ingestion_batch_id, processing_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                [
                    source_type,
                    source_software,
                    file_name,
                    file_hash,
                    idx,
                    raw_json,
                    headers_json,
                    batch_id,
                ],
            )

        count = len(rows)
        self._log_audit("bronze_ingest", "bronze", batch_id, "success", count, None, 0)
        return count

    # ------------------------------------------------------------------
    # Step 2 — Silver
    # ------------------------------------------------------------------
    def _step_silver(
        self, batch_id: str, result: PipelineResult
    ) -> tuple[int, int, float]:
        pending = self.conn.execute(
            """
            SELECT bronze_id, raw_content
            FROM bronze_transactions
            WHERE ingestion_batch_id = ? AND processing_status = 'pending'
            """,
            [batch_id],
        ).fetchall()

        silver_count = 0
        quarantine_count = 0
        quality_sum = 0.0

        for bronze_id, raw_json in pending:
            try:
                row = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                self._quarantine(bronze_id, "invalid_json", raw_json, str(exc))
                self._update_bronze_status(bronze_id, "quarantined")
                quarantine_count += 1
                continue

            parsed = self._normalise_row(row)

            quality = self._compute_quality(parsed)

            if quality < 0.3:
                reason = f"quality_below_threshold ({quality:.2f})"
                self._quarantine(bronze_id, reason, raw_json, None)
                self._update_bronze_status(bronze_id, "quarantined")
                quarantine_count += 1
                continue

            # Detect language (simple heuristic: any Arabic/Urdu char -> "ur")
            desc_text = parsed.get("description") or ""
            lang = "ur" if re.search(r"[؀-ۿ]", desc_text) else "en"

            # PII masking
            desc_masked, pii_masked, pii_types = self._mask_pii(desc_text)

            txn_date = parsed.get("date")
            year_month = txn_date.strftime("%Y-%m") if txn_date else None
            fiscal_year = self._fiscal_year(txn_date) if txn_date else None

            self.conn.execute(
                """
                INSERT INTO silver_transactions
                    (bronze_id, transaction_date, year_month, fiscal_year,
                     description, description_masked, vendor, category,
                     amount_debit, amount_credit, currency,
                     language_detected, pii_masked, pii_types_found,
                     quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PKR', ?, ?, ?, ?)
                """,
                [
                    bronze_id,
                    txn_date,
                    year_month,
                    fiscal_year,
                    desc_text,
                    desc_masked,
                    parsed.get("vendor"),
                    parsed.get("category"),
                    parsed.get("debit", 0.0),
                    parsed.get("credit", 0.0),
                    lang,
                    pii_masked,
                    pii_types if pii_types else None,
                    quality,
                ],
            )
            self._update_bronze_status(bronze_id, "normalised")
            silver_count += 1
            quality_sum += quality

        avg_quality = quality_sum / silver_count if silver_count else 0.0
        self._log_audit(
            "silver_normalise", "silver", batch_id, "success", silver_count, None, 0
        )
        return silver_count, quarantine_count, round(avg_quality, 4)

    # ------------------------------------------------------------------
    # Step 3 — Gold
    # ------------------------------------------------------------------
    def _step_gold(self, batch_id: str, result: PipelineResult) -> int:
        eligible = self.conn.execute(
            """
            SELECT s.silver_id, s.bronze_id, s.transaction_date, s.year_month,
                   s.fiscal_year, s.description_masked, s.vendor, s.category,
                   s.amount_debit, s.amount_credit, s.quality_score
            FROM silver_transactions s
            JOIN bronze_transactions b ON s.bronze_id = b.bronze_id
            WHERE b.ingestion_batch_id = ? AND s.quality_score >= 0.7
            """,
            [batch_id],
        ).fetchall()

        count = 0
        for row in eligible:
            (
                silver_id, bronze_id, txn_date, year_month, fiscal_year,
                desc_masked, vendor, category, debit, credit, quality,
            ) = row

            # Build embedding text
            amount = debit if debit else credit
            direction = "paid to" if debit else "received from"
            date_str = txn_date.strftime("%d %b %Y") if txn_date else "unknown date"
            embedding_text = (
                f"On {date_str}, PKR {amount:,.0f} was {direction} "
                f"{vendor or 'unknown'} — {category or 'uncategorised'}"
            )

            # FBR classification
            fbr_cat, fbr_tax = self._classify_fbr(desc_masked, category)

            # Category confidence (simple: 0.9 if we found a category, else 0.5)
            cat_confidence = 0.9 if category else 0.5

            self.conn.execute(
                """
                INSERT INTO gold_transactions
                    (silver_id, bronze_id, transaction_date, year_month,
                     fiscal_year, description_masked, vendor, category,
                     category_confidence, amount_debit, amount_credit,
                     currency, embedding_text, fbr_category,
                     fbr_tax_applicable, quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PKR', ?, ?, ?, ?)
                """,
                [
                    silver_id, bronze_id, txn_date, year_month, fiscal_year,
                    desc_masked, vendor, category, cat_confidence,
                    debit, credit, embedding_text, fbr_cat, fbr_tax, quality,
                ],
            )
            count += 1

        self._log_audit(
            "gold_promote", "gold", batch_id, "success", count, None, 0
        )
        return count

    # ------------------------------------------------------------------
    # Helpers — CSV reading
    # ------------------------------------------------------------------
    def _read_csv(self, file_path: str) -> list[dict]:
        encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc, newline="") as f:
                    content = f.read()
                reader = csv.DictReader(io.StringIO(content))
                rows = [dict(r) for r in reader]
                return rows
            except (UnicodeDecodeError, UnicodeError):
                continue
        return []

    def _file_hash(self, file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Helpers — Normalisation
    # ------------------------------------------------------------------
    def _normalise_row(self, row: dict) -> dict:
        """Extract structured fields from a raw row dict."""
        keys_lower = {k.lower().strip(): k for k in row}

        parsed: dict = {}

        # --- Date ---
        date_keys = ["date", "tarikh", "taareekh", "تاریخ"]
        for dk in date_keys:
            for kl, ko in keys_lower.items():
                if dk in kl:
                    parsed["date"] = self._parse_date(row[ko])
                    break
            if "date" in parsed:
                break

        # --- Description ---
        desc_keys = [
            "description", "narration", "particulars",
            "tafseelat", "تفصیل",
            "تفصیلات",
        ]
        for dk in desc_keys:
            for kl, ko in keys_lower.items():
                if dk in kl:
                    parsed["description"] = (row[ko] or "").strip()
                    break
            if "description" in parsed:
                break

        # --- Vendor ---
        vendor_keys = [
            "vendor", "party", "name", "naam",
            "نام",
        ]
        for vk in vendor_keys:
            for kl, ko in keys_lower.items():
                if vk in kl:
                    parsed["vendor"] = (row[ko] or "").strip() or None
                    break
            if "vendor" in parsed:
                break

        # --- Amount ---
        parsed["debit"] = 0.0
        parsed["credit"] = 0.0

        # Check for explicit debit/credit columns
        amount_debit_keys = ["debit", "dr"]
        amount_credit_keys = ["credit", "cr"]
        has_explicit = False
        for dk in amount_debit_keys:
            for kl, ko in keys_lower.items():
                if dk == kl:
                    val = self._parse_amount(row[ko])
                    if val != 0.0:
                        parsed["debit"] = abs(val)
                        has_explicit = True
                    break

        for ck in amount_credit_keys:
            for kl, ko in keys_lower.items():
                if ck == kl:
                    val = self._parse_amount(row[ko])
                    if val != 0.0:
                        parsed["credit"] = abs(val)
                        has_explicit = True
                    break

        if not has_explicit:
            # Look for a single amount column + type column
            amount_keys = ["amount", "raqam", "رقم"]
            for ak in amount_keys:
                for kl, ko in keys_lower.items():
                    if ak in kl:
                        val = self._parse_amount(row[ko])
                        # Check for type column
                        txn_type = self._find_type(row, keys_lower)
                        if txn_type and "credit" in txn_type.lower():
                            parsed["credit"] = abs(val)
                        else:
                            parsed["debit"] = abs(val)
                        has_explicit = True
                        break
                if has_explicit:
                    break

        # --- Category (infer from description) ---
        desc = parsed.get("description", "").lower()
        parsed["category"] = self._infer_category(desc)

        return parsed

    def _find_type(self, row: dict, keys_lower: dict) -> str | None:
        type_keys = ["type", "txn_type", "transaction_type"]
        for tk in type_keys:
            for kl, ko in keys_lower.items():
                if tk in kl:
                    return (row[ko] or "").strip()
        return None

    def _parse_date(self, val: str | None) -> datetime | None:
        if not val:
            return None
        val = val.strip()
        formats = ["%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"]
        for fmt in formats:
            try:
                return datetime.strptime(val, fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _parse_amount(self, val: str | None) -> float:
        if not val:
            return 0.0
        val = str(val).strip()
        # Remove PKR prefix and commas
        val = re.sub(r"(?i)^pkr\s*", "", val)
        val = val.replace(",", "")
        # Handle parentheses as negative
        if val.startswith("(") and val.endswith(")"):
            val = "-" + val[1:-1]
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def _infer_category(self, description: str) -> str | None:
        if not description:
            return None
        desc_lower = description.lower()
        for keyword, (cat, _) in _FBR_CATEGORIES.items():
            if keyword in desc_lower:
                return cat
        return None

    def _fiscal_year(self, dt: datetime | None) -> str | None:
        """Pakistani fiscal year: July to June."""
        if not dt:
            return None
        if dt.month >= 7:
            return f"{dt.year}-{dt.year + 1}"
        else:
            return f"{dt.year - 1}-{dt.year}"

    # ------------------------------------------------------------------
    # Helpers — PII
    # ------------------------------------------------------------------
    def _mask_pii(self, text: str) -> tuple[str, bool, str | None]:
        """Mask CNIC and phone numbers. Return (masked_text, was_masked, types)."""
        pii_types: list[str] = []
        masked = text

        # CNIC: 12345-1234567-1
        if re.search(r"\d{5}-\d{7}-\d", masked):
            masked = re.sub(r"\d{5}-\d{7}-\d", "[CNIC]", masked)
            pii_types.append("CNIC")

        # Phone: 03xxxxxxxxx or +92xxxxxxxxxx
        if re.search(r"03\d{9}", masked):
            masked = re.sub(r"03\d{9}", "[PHONE]", masked)
            pii_types.append("PHONE")
        if re.search(r"\+92\d{10}", masked):
            masked = re.sub(r"\+92\d{10}", "[PHONE]", masked)
            if "PHONE" not in pii_types:
                pii_types.append("PHONE")

        was_masked = len(pii_types) > 0
        return masked, was_masked, ",".join(pii_types) if pii_types else None

    # ------------------------------------------------------------------
    # Helpers — Quality
    # ------------------------------------------------------------------
    def _compute_quality(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("date"):
            score += 0.3
        if parsed.get("debit", 0) != 0 or parsed.get("credit", 0) != 0:
            score += 0.3
        if parsed.get("description"):
            score += 0.2
        if parsed.get("vendor"):
            score += 0.1
        # +0.1 if no PII in description
        desc = parsed.get("description", "")
        has_pii = bool(
            re.search(r"\d{5}-\d{7}-\d", desc)
            or re.search(r"03\d{9}", desc)
            or re.search(r"\+92\d{10}", desc)
        )
        if not has_pii:
            score += 0.1
        return round(score, 2)

    # ------------------------------------------------------------------
    # Helpers — FBR
    # ------------------------------------------------------------------
    def _classify_fbr(
        self, description: str | None, category: str | None
    ) -> tuple[str | None, bool]:
        combined = ((description or "") + " " + (category or "")).lower()
        for keyword, (fbr_cat, taxable) in _FBR_CATEGORIES.items():
            if keyword in combined:
                return fbr_cat, taxable
        return None, False

    # ------------------------------------------------------------------
    # Helpers — DB operations
    # ------------------------------------------------------------------
    def _init_tables(self) -> None:
        for ddl in _DDL_STATEMENTS:
            self.conn.execute(ddl)

    def _update_bronze_status(self, bronze_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE bronze_transactions SET processing_status = ? WHERE bronze_id = ?",
            [status, bronze_id],
        )

    def _quarantine(
        self,
        bronze_id: str,
        reason: str,
        raw_content: str | None,
        error_detail: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO silver_quarantine (bronze_id, reason, raw_content, error_detail)
            VALUES (?, ?, ?, ?)
            """,
            [bronze_id, reason, raw_content, error_detail],
        )

    def _log_audit(
        self,
        operation: str,
        source_layer: str,
        batch_id: str | None,
        status: str,
        rows_affected: int,
        error_detail: str | None,
        duration_ms: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO pipeline_audit_log
                (operation, source_layer, batch_id, status,
                 rows_affected, error_detail, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                operation, source_layer, batch_id, status,
                rows_affected, error_detail, duration_ms,
            ],
        )

    @staticmethod
    def _elapsed_ms(t0_ns: int) -> int:
        return int((time.perf_counter_ns() - t0_ns) / 1_000_000)
