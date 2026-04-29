"""
schemas/ingestion.py
--------------------
Pydantic v2 schemas for ingestion endpoints.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class PIISummary(BaseModel):
    """
    Privacy Firewall (M13) scan results for an ingestion job.

    These are AGGREGATE statistics only — no raw PII values are ever
    returned through the API. The frontend can use this to show
    a privacy badge like "✅ No PII detected" or "⚠ 3 rows masked".
    """
    total_rows_scanned: int = 0
    rows_with_pii: int = 0
    pii_percentage: float = 0.0
    pii_types_detected: List[str] = []
    flagged_columns: List[str] = []


class IngestionJobResponse(BaseModel):
    id: str
    org_id: str
    filename: str
    file_sha256: str
    file_size_bytes: int
    mime_type: Optional[str]
    status: str
    rows_total: int
    rows_imported: int
    rows_skipped: int
    rows_failed: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    pii_summary: Optional[PIISummary] = None   # M13: Privacy Firewall report

    model_config = {"from_attributes": True}


class IngestionUploadResponse(BaseModel):
    job: IngestionJobResponse
    warnings: List[str] = []
    duplicate: bool = False
