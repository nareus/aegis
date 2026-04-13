"""Briefing API endpoints -- stubs for Phase 5."""

from fastapi import APIRouter

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.post("/run")
async def trigger_run():
    """Trigger a briefing run. Returns run_id immediately."""
    # Will delegate to BriefingService in Phase 5
    return {"status": "not_implemented"}


@router.get("/latest")
async def get_latest():
    """Get the latest successful briefing."""
    return {"status": "not_implemented"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get a specific run by ID."""
    return {"status": "not_implemented"}


@router.get("/runs")
async def list_runs(limit: int = 10):
    """List recent runs."""
    return {"status": "not_implemented"}
