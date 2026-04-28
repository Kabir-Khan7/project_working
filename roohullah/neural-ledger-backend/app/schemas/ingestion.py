"""
schemas/ingestion.py
--------------------
Pydantic v2 schemas for ingestion endpoints.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


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

    model_config = {"from_attributes": True}


class IngestionUploadResponse(BaseModel):
    job: IngestionJobResponse
    warnings: List[str] = []
    duplicate: bool = False
