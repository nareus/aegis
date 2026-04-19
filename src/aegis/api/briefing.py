"""Briefing API endpoints."""

from fastapi import APIRouter, HTTPException

from aegis.briefing.service import BriefingService
from aegis.db.repository import BriefingRunRepository

router = APIRouter(prefix="/briefing", tags=["briefing"])
_service: BriefingService | None = None


def _svc() -> BriefingService:
    global _service
    if _service is None:
        _service = BriefingService()
    return _service


@router.post("/run", status_code=202)
async def trigger_run(trigger_source: str = "api") -> dict:
    """Trigger a briefing run. Runs synchronously and returns the result."""
    return await _svc().run(trigger_source=trigger_source)


@router.get("/latest")
async def get_latest() -> dict:
    """Get the latest successful briefing."""
    repo = BriefingRunRepository()
    result = await repo.get_latest()
    if result is None:
        raise HTTPException(status_code=404, detail="No briefings found")
    return result


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Get a specific briefing run by ID."""
    repo = BriefingRunRepository()
    result = await repo.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@router.get("/runs")
async def list_runs(limit: int = 10) -> list[dict]:
    """List recent briefing runs."""
    repo = BriefingRunRepository()
    return await repo.list_recent(limit)
