"""
api/v1/ingest.py
----------------
Routes:
  POST /api/v1/orgs/{org_id}/ingest/upload   → upload xlsx / csv
  GET  /api/v1/orgs/{org_id}/ingest/jobs     → list past ingestion jobs
  GET  /api/v1/orgs/{org_id}/ingest/jobs/{job_id} → single job detail
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.core.dependencies import CurrentUser, DBSession, require_org_member
from app.models.ingestion import IngestionJob
from app.schemas.ingestion import IngestionJobResponse, IngestionUploadResponse
from app.services.ingestion import ingest_file

router = APIRouter(prefix="/orgs/{org_id}/ingest", tags=["Ingestion"])

MAX_FILE_BYTES = 25 * 1024 * 1024   # 25 MB cap


# ── Upload ────────────────────────────────────────────────────────────────────
@router.post("/upload", response_model=IngestionUploadResponse, status_code=201)
async def upload_file(
    org_id: str,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    _=Depends(require_org_member("member")),
):
    if not file.filename:
        raise HTTPException(400, "Filename missing")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_FILE_BYTES // (1024*1024)} MB limit",
        )

    result = await ingest_file(
        db=db,
        org_id=org_id,
        user_id=user.id,
        filename=file.filename,
        content=content,
        mime_type=file.content_type,
    )

    return IngestionUploadResponse(
        job=result.job,
        warnings=result.warnings,
        duplicate=result.duplicate,
    )


# ── List jobs ─────────────────────────────────────────────────────────────────
@router.get("/jobs", response_model=list[IngestionJobResponse])
async def list_jobs(
    org_id: str,
    db: DBSession,
    user: CurrentUser,
    _=Depends(require_org_member("viewer")),
):
    result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.org_id == org_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(100)
    )
    return result.scalars().all()


# ── Job detail ────────────────────────────────────────────────────────────────
@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_job(
    org_id: str,
    job_id: str,
    db: DBSession,
    user: CurrentUser,
    _=Depends(require_org_member("viewer")),
):
    job = await db.get(IngestionJob, job_id)
    if not job or job.org_id != org_id:
        raise HTTPException(404, "Ingestion job not found")
    return job
