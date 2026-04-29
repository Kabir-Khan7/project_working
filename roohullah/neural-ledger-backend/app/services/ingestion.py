"""
services/ingestion.py
---------------------
Orchestrates the full ingestion pipeline:

    bytes  →  hash + dedupe check
           →  parse to DataFrame
           →  validate + normalise
           →  persist Transactions + IngestionJob
           →  return summary
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import IngestionJob
from app.models.transaction import Transaction
from app.services.parser import (
    ParserError, UnsupportedFormatError, iter_rows, parse_file,
)
from app.services.pii_detector import mask_row, scan_dataframe, scan_row


class IngestionResult:
    """Plain DTO returned to the route handler."""
    def __init__(
        self, *,
        job: IngestionJob,
        warnings: list[str],
        duplicate: bool = False,
    ):
        self.job = job
        self.warnings = warnings
        self.duplicate = duplicate


# ── Public entry point ────────────────────────────────────────────────────────
async def ingest_file(
    *,
    db: AsyncSession,
    org_id: str,
    user_id: str,
    filename: str,
    content: bytes,
    mime_type: str | None = None,
) -> IngestionResult:
    """
    Process an uploaded file end-to-end.

    Idempotency: if (org_id, file_sha256) already exists, returns the existing
    job with duplicate=True instead of re-processing.
    """
    sha = hashlib.sha256(content).hexdigest()

    # ── 1. Idempotency check ──────────────────────────────────────────────────
    existing = await db.execute(
        select(IngestionJob).where(
            IngestionJob.org_id == org_id,
            IngestionJob.file_sha256 == sha,
        )
    )
    job_existing = existing.scalar_one_or_none()
    if job_existing:
        return IngestionResult(
            job=job_existing,
            warnings=[f"File already ingested on {job_existing.created_at:%Y-%m-%d}"],
            duplicate=True,
        )

    # ── 2. Create job row (status=processing) ─────────────────────────────────
    job = IngestionJob(
        org_id=org_id,
        uploaded_by=user_id,
        filename=filename,
        file_sha256=sha,
        file_size_bytes=len(content),
        mime_type=mime_type,
        status="processing",
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()    # get job.id

    warnings: list[str] = []

    # ── 3. Parse ──────────────────────────────────────────────────────────────
    try:
        df, parse_warnings = parse_file(content=content, filename=filename)
        warnings.extend(parse_warnings)
    except (ParserError, UnsupportedFormatError) as e:
        job.status = "failed"
        job.error_message = str(e)
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)
        return IngestionResult(job=job, warnings=warnings)

    job.rows_total = len(df)

    # ── 4. Privacy Firewall (M13) — scan entire DataFrame for PII ────────────
    #
    # Why scan first, before persisting?
    # We need aggregate stats at the job level (e.g. "12 rows had phone
    # numbers") so we scan the whole DataFrame in one pass.
    # Then at row level, we mask PII before writing to DB.
    #
    pii_summary = scan_dataframe(df)
    job.pii_summary = pii_summary

    if pii_summary["rows_with_pii"] > 0:
        warnings.append(
            f"Privacy Firewall: {pii_summary['rows_with_pii']} row(s) contained "
            f"PII ({', '.join(pii_summary['pii_types_detected'])}). "
            f"Sensitive values have been masked before storage."
        )

    # ── 5. Persist transactions (with row-level dedupe + PII masking) ─────────
    seen_hashes: set[str] = set()
    imported = skipped = failed = 0

    for parsed in iter_rows(df):
        try:
            # M13: scan this row, then mask PII fields before hashing/storing
            row_dict = {
                "description": parsed.description,
                "party_name":  parsed.party_name,
                "reference":   parsed.reference,
            }
            row_scan = scan_row(row_dict)
            if row_scan.has_pii:
                masked = mask_row(row_dict, row_scan)
                # Replace ParsedRow fields with masked versions
                description = masked["description"]
                party_name  = masked["party_name"]
                reference   = masked["reference"]
            else:
                description = parsed.description
                party_name  = parsed.party_name
                reference   = parsed.reference

            row_hash = _row_hash(
                parsed.txn_date, description, parsed.amount,
                party_name, reference,
            )

            # In-batch dedupe
            if row_hash in seen_hashes:
                skipped += 1
                continue
            seen_hashes.add(row_hash)

            # Cross-batch dedupe (already in DB?)
            existing_tx = await db.execute(
                select(Transaction.id).where(
                    Transaction.org_id == org_id,
                    Transaction.source_row_hash == row_hash,
                ).limit(1)
            )
            if existing_tx.scalar_one_or_none():
                skipped += 1
                continue

            db.add(Transaction(
                org_id=org_id,
                ingestion_job_id=job.id,
                source_row_hash=row_hash,
                txn_date=parsed.txn_date.date(),
                description=description,
                party_name=party_name,
                reference=reference,
                amount=parsed.amount,
                currency=parsed.currency,
                direction=parsed.direction,
            ))
            imported += 1

        except Exception:   # noqa: BLE001  — we count failures, never crash the whole import
            failed += 1
            continue

    # ── 5. Finalise job ───────────────────────────────────────────────────────
    job.rows_imported = imported
    job.rows_skipped = skipped
    job.rows_failed = failed
    job.status = "completed" if failed == 0 else "completed"
    job.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(job)

    return IngestionResult(job=job, warnings=warnings)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _row_hash(
    txn_date,
    description: str,
    amount: Decimal,
    party_name: str | None,
    reference: str | None,
) -> str:
    """SHA-256 of the canonical row tuple — used to dedupe re-uploads."""
    payload = "|".join([
        str(txn_date),
        (description or "").strip().lower(),
        f"{amount:.2f}",
        (party_name or "").strip().lower(),
        (reference or "").strip().lower(),
    ])
    return hashlib.sha256(payload.encode()).hexdigest()
