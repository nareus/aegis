"""REST endpoints for the job tracker."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aegis.jobs.service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])
_service: JobService | None = None


def _svc() -> JobService:
    global _service
    if _service is None:
        _service = JobService()
    return _service


class AddJobRequest(BaseModel):
    text: str
    url: str | None = None


class UpdateStatusRequest(BaseModel):
    status: str
    notes: str | None = None


@router.post("", status_code=201)
async def add_job(body: AddJobRequest) -> dict:
    """Parse a JD and add to tracker. Returns job_id + fit analysis."""
    return await _svc().add_job(body.text, url=body.url)


@router.get("")
async def list_jobs(status: str | None = None) -> list[dict]:
    """List all tracked jobs, optionally filtered by status."""
    return await _svc().list_jobs(status=status)


@router.get("/follow-ups")
async def get_follow_ups(stale_days: int = 7) -> list[dict]:
    """Jobs that need a follow-up (stale for N days)."""
    return await _svc().get_follow_ups(stale_days)


@router.get("/top-fits")
async def get_top_fits(min_score: float = 0.7) -> list[dict]:
    """Saved jobs with fit_score >= min_score, not yet applied."""
    return await _svc().get_top_fits(min_score)


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict:
    """Get full details of a single job application."""
    job = await _svc().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/{job_id}/status")
async def update_status(job_id: str, body: UpdateStatusRequest) -> dict:
    """Update the status of a job application."""
    ok = await _svc().update_status(job_id, body.status, notes=body.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"updated": True}
