"""
Gold Writer — Promotes quality-checked silver rows to enriched gold transactions.

Part of the Medallion Architecture (Bronze -> Silver -> Gold) pipeline.
Reads eligible rows from silver_transactions (quality_score >= 0.7), enriches
them with embedding text, FBR tax classification, and category inference,
then writes to gold_transactions. Also pre-computes period summaries.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PromotionResult:
    """Result of a batch promotion run."""

    rows_eligible: int = 0
    rows_promoted: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def format_amount(amount: float, currency: str = "PKR") -> str:
    """Format a numeric amount with thousands separator.

    >>> format_amount(5000, "PKR")
    'PKR 5,000'
    >>> format_amount(1234567.89, "PKR")
    'PKR 1,234,568'
    """
    return f"{currency} {round(amount):,}"


def format_date_human(dt: date | datetime | str | None) -> str:
    """Format a date as '15 Jan 2024'.

    Accepts date, datetime, or ISO-format string.

    >>> format_date_human(date(2024, 1, 15))
    '15 Jan 2024'
    """
    if dt is None:
        return "Unknown date"
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, "%Y-%m-%d").date()
        except ValueError:
            return dt
    if isinstance(dt, datetime):
        dt = dt.date()
    if not hasattr(dt, "strftime"):
        return str(dt)
    # %-d is Linux-only; %#d is Windows-only. Use f-string for portability.
    return f"{dt.day} {dt.strftime('%b %Y')}"


def classify_fbr(category: str | None) -> tuple[str | None, bool]:
    """Classify a transaction category into FBR withholding tax section.

    Returns (fbr_category, fbr_tax_applicable).

    >>> classify_fbr("Rent")
    ('Section 155 - Rent', True)
    >>> classify_fbr("Unknown")
    (None, False)
    """
    if not category:
        return None, False

    cat_lower = category.lower()

    if "rent" in cat_lower:
        return "Section 155 - Rent", True
    if "salary" in cat_lower or "wages" in cat_lower:
        return "Section 149 - Salary", True
    if any(kw in cat_lower for kw in ("fuel", "supplies", "goods")):
        return "Section 153 - Goods", True
    if any(kw in cat_lower for kw in ("consulting", "legal", "services")):
        return "Section 153 - Services", True

    return None, False


def build_embedding_text(row: dict) -> str:
    """Build a natural-language sentence from a silver row for RAG embedding.

    Format:
      "On {date}, {currency} {amount} was {paid to/received from} {vendor} — {category}"
    If no vendor:
      "On {date}, {currency} {amount} was debited — {category}"
    If no category: omit the dash part.

    >>> build_embedding_text({
    ...     "transaction_date": date(2024, 1, 15),
    ...     "currency": "PKR",
    ...     "amount_debit": 5000.0,
    ...     "amount_credit": 0.0,
    ...     "vendor": "Shell Clifton",
    ...     "category": "Fuel & Transport",
    ...     "description_masked": "Fuel purchase",
    ... })
    'On 15 Jan 2024, PKR 5,000 was paid to Shell Clifton \\u2014 Fuel & Transport'
    """
    tx_date = row.get("transaction_date")
    date_str = format_date_human(tx_date)

    debit = row.get("amount_debit") or 0.0
    credit = row.get("amount_credit") or 0.0
    currency = row.get("currency") or "PKR"

    # Determine direction and amount
    if debit > 0:
        amount = debit
        direction = "debit"
    else:
        amount = credit
        direction = "credit"

    amount_str = format_amount(amount, currency)
    vendor = row.get("vendor")
    category = row.get("category")

    # Build the action phrase
    if vendor:
        if direction == "debit":
            action = f"paid to {vendor}"
        else:
            action = f"received from {vendor}"
    else:
        if direction == "debit":
            action = "debited"
        else:
            action = "credited"

    sentence = f"On {date_str}, {amount_str} was {action}"

    if category:
        sentence += f" — {category}"

    return sentence


# ---------------------------------------------------------------------------
# GoldWriter
# ---------------------------------------------------------------------------

_QUALITY_THRESHOLD = 0.7


class GoldWriter:
    """Promotes eligible silver rows to gold_transactions with enrichment."""

    def __init__(self, quality_threshold: float = _QUALITY_THRESHOLD) -> None:
        self.quality_threshold = quality_threshold

    # ----- public API -------------------------------------------------------

    def promote_batch(self, conn: Any, batch_id: str) -> PromotionResult:
        """Promote all eligible silver rows for *batch_id*.

        Eligible means quality_score >= threshold.  Rows already present in
        gold_transactions (by silver_id) are silently skipped.
        """
        t0 = time.time()
        result = PromotionResult()

        try:
            rows = conn.execute(
                """
                SELECT s.*
                FROM silver_transactions s
                LEFT JOIN gold_transactions g ON g.silver_id = s.silver_id
                WHERE s.silver_id LIKE ?
                  AND g.silver_id IS NULL
                """,
                [f"{batch_id}%"],
            ).fetchall()

            columns = [desc[0] for desc in conn.description]
            rows_as_dicts = [dict(zip(columns, r)) for r in rows]
        except Exception as exc:
            result.errors.append(f"Query failed: {exc}")
            result.duration_ms = int((time.time() - t0) * 1000)
            self._log_audit(conn, "promote_batch", batch_id, "error",
                            0, str(exc), result.duration_ms)
            return result

        for row in rows_as_dicts:
            qs = row.get("quality_score") or 0.0
            if qs >= self.quality_threshold:
                result.rows_eligible += 1
                try:
                    promoted = self.promote_row(conn, row)
                    if promoted:
                        result.rows_promoted += 1
                except Exception as exc:
                    result.errors.append(
                        f"Row {row.get('silver_id')}: {exc}"
                    )
            else:
                result.rows_skipped += 1

        result.duration_ms = int((time.time() - t0) * 1000)

        status = "success" if not result.errors else "partial"
        self._log_audit(
            conn, "promote_batch", batch_id, status,
            result.rows_promoted, None, result.duration_ms,
        )
        return result

    def promote_row(self, conn: Any, silver_row: dict) -> bool:
        """Promote a single silver row to gold_transactions.

        Returns True if the row was inserted, False otherwise.
        """
        qs = silver_row.get("quality_score") or 0.0
        if qs < self.quality_threshold:
            return False

        embedding_text = build_embedding_text(silver_row)
        category = silver_row.get("category")
        fbr_cat, fbr_tax = classify_fbr(category)
        gold_id = str(uuid.uuid4())

        conn.execute(
            """
            INSERT INTO gold_transactions (
                transaction_id, silver_id, bronze_id,
                transaction_date, year_month, fiscal_year,
                description_masked, vendor, category,
                subcategory, category_confidence,
                amount_debit, amount_credit, currency,
                embedding_text, fbr_category, fbr_tax_applicable,
                quality_score, qdrant_indexed, gold_version
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
            """,
            [
                gold_id,
                silver_row.get("silver_id"),
                silver_row.get("bronze_id"),
                silver_row.get("transaction_date"),
                silver_row.get("year_month"),
                silver_row.get("fiscal_year"),
                silver_row.get("description_masked"),
                silver_row.get("vendor"),
                category,
                None,  # subcategory — reserved for ML enrichment
                0.0,   # category_confidence — reserved for ML
                silver_row.get("amount_debit") or 0.0,
                silver_row.get("amount_credit") or 0.0,
                silver_row.get("currency") or "PKR",
                embedding_text,
                fbr_cat,
                fbr_tax,
                qs,
                False,
                1,
            ],
        )
        return True

    # ----- internal ---------------------------------------------------------

    @staticmethod
    def _log_audit(
        conn: Any,
        operation: str,
        batch_id: str | None,
        status: str,
        rows_affected: int,
        error_detail: str | None,
        duration_ms: int,
    ) -> None:
        """Write an entry to pipeline_audit_log."""
        try:
            conn.execute(
                """
                INSERT INTO pipeline_audit_log
                    (log_id, operation, source_layer, batch_id,
                     status, rows_affected, error_detail, duration_ms)
                VALUES (?, ?, 'gold', ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    operation,
                    batch_id,
                    status,
                    rows_affected,
                    error_detail,
                    duration_ms,
                ],
            )
        except Exception:
            pass  # audit logging must never crash the pipeline


# ---------------------------------------------------------------------------
# PeriodSummaryBuilder
# ---------------------------------------------------------------------------

class PeriodSummaryBuilder:
    """Pre-compute period summaries from gold_transactions."""

    def build_monthly_summaries(self, conn: Any) -> int:
        """Compute monthly summaries from gold data.

        Uses INSERT OR REPLACE so the operation is idempotent.
        Returns the number of summary rows written.
        """
        # Gather per-month aggregates
        month_rows = conn.execute(
            """
            SELECT
                year_month,
                fiscal_year,
                SUM(amount_credit) AS total_income,
                SUM(amount_debit) AS total_expenses,
                SUM(amount_credit) - SUM(amount_debit) AS net_amount,
                COUNT(*) AS transaction_count
            FROM gold_transactions
            GROUP BY year_month, fiscal_year
            ORDER BY year_month
            """
        ).fetchall()

        if not month_rows:
            return 0

        month_cols = [d[0] for d in conn.description]
        months = [dict(zip(month_cols, r)) for r in month_rows]

        # Category breakdowns per month
        cat_rows = conn.execute(
            """
            SELECT
                year_month,
                category,
                SUM(amount_debit) + SUM(amount_credit) AS total
            FROM gold_transactions
            GROUP BY year_month, category
            ORDER BY year_month, category
            """
        ).fetchall()

        cat_by_month: dict[str, dict[str, float]] = {}
        for ym, cat, total in cat_rows:
            cat_by_month.setdefault(ym, {})[cat or "Uncategorised"] = total

        # Build summaries with prior-period comparison
        written = 0
        prev_net: float | None = None

        for m in months:
            ym = m["year_month"]
            net = m["net_amount"] or 0.0

            vs_prior: float | None = None
            anomaly = False
            if prev_net is not None and prev_net != 0:
                vs_prior = round((net - prev_net) / abs(prev_net) * 100, 2)
                anomaly = abs(vs_prior) > 50

            # Derive period start / end from year_month "YYYY-MM"
            year, month_num = int(ym[:4]), int(ym[5:7])
            period_start = date(year, month_num, 1)
            # Last day of month
            if month_num == 12:
                period_end = date(year, 12, 31)
            else:
                period_end = date(year, month_num + 1, 1).replace(day=1)
                period_end = date(
                    period_end.year, period_end.month, 1
                ).__class__(period_end.year, period_end.month, 1)
                # Subtract one day to get last day of current month
                from datetime import timedelta
                period_end = date(year, month_num + 1, 1) - timedelta(days=1)

            breakdown = json.dumps(cat_by_month.get(ym, {}))

            # Delete existing then insert (DuckDB doesn't support INSERT OR REPLACE)
            conn.execute(
                """
                DELETE FROM gold_period_summaries
                WHERE period_type = 'monthly' AND period_start = ?
                """,
                [period_start],
            )
            conn.execute(
                """
                INSERT INTO gold_period_summaries (
                    summary_id, period_type, period_start, period_end,
                    year_month, fiscal_year,
                    total_income, total_expenses, net_amount,
                    transaction_count, category_breakdown,
                    anomaly_flag, vs_prior_period_pct
                ) VALUES (?, 'monthly', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    period_start,
                    period_end,
                    ym,
                    m.get("fiscal_year"),
                    m["total_income"] or 0.0,
                    m["total_expenses"] or 0.0,
                    net,
                    m["transaction_count"],
                    breakdown,
                    anomaly,
                    vs_prior,
                ],
            )
            written += 1
            prev_net = net

        return written
