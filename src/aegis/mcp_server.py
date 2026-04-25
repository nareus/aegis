"""MCP server -- tools/resources/prompts wired to Aegis services."""

from fastmcp import FastMCP
from loguru import logger

from aegis.briefing.service import BriefingService
from aegis.jobs.service import JobService
from aegis.logging import setup_logging

mcp = FastMCP("Aegis")

_briefing_service: BriefingService | None = None
_job_service: JobService | None = None


def _briefing() -> BriefingService:
    global _briefing_service
    if _briefing_service is None:
        _briefing_service = BriefingService()
    return _briefing_service


def _jobs() -> JobService:
    global _job_service
    if _job_service is None:
        _job_service = JobService()
    return _job_service


# ---------------------------------------------------------------------------
# Briefing tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def run_briefing(trigger_source: str = "mcp") -> dict:
    """Run a full Aegis daily briefing and return the result.

    Args:
        trigger_source: How the run was triggered (default: "mcp").

    Returns:
        run_id, status, briefing_markdown, quality_score, cost breakdown.
    """
    logger.info("MCP: run_briefing triggered")
    return await _briefing().run(trigger_source=trigger_source)


@mcp.tool()
async def get_latest_briefing() -> dict:
    """Return the most recent successful briefing run."""
    from aegis.db.repository import BriefingRunRepository
    repo = BriefingRunRepository()
    result = await repo.get_latest()
    if result is None:
        return {"error": "No briefings found. Run run_briefing first."}
    return result


# ---------------------------------------------------------------------------
# Job tracker tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def add_job(text: str, url: str = "") -> dict:
    """Parse a job description and add it to the job tracker.

    Paste the full JD text (copied from LinkedIn or any site). Aegis will:
    - Extract company, role, tech stack, salary, location
    - Score fit against your profile (0-1)
    - Save to the tracker

    Args:
        text: Full job description text.
        url:  Optional source URL (e.g. LinkedIn posting URL).

    Returns:
        job_id, company, role, fit_score, fit_analysis.
    """
    logger.info("MCP: add_job for url={}", url or "(no url)")
    return await _jobs().add_job(text, url=url or None)


@mcp.tool()
async def list_jobs(status: str = "") -> list[dict]:
    """List all tracked job applications.

    Args:
        status: Filter by status: saved | applied | phone_screen | technical |
                final | offer | rejected | withdrawn. Leave empty for all.
    """
    return await _jobs().list_jobs(status=status or None)


@mcp.tool()
async def update_job_status(job_id: str, status: str, notes: str = "") -> dict:
    """Update the status of a tracked job application.

    Args:
        job_id: UUID of the job from add_job or list_jobs.
        status: New status (saved | applied | phone_screen | technical |
                final | offer | rejected | withdrawn).
        notes:  Optional progress notes.

    Returns:
        {"updated": true} or {"updated": false, "error": "..."}.
    """
    ok = await _jobs().update_status(job_id, status, notes=notes or None)
    if ok:
        return {"updated": True}
    return {"updated": False, "error": "job not found"}


@mcp.tool()
async def get_follow_ups(stale_days: int = 7) -> list[dict]:
    """Return job applications that need follow-up.

    Args:
        stale_days: How many days since last update before flagging (default 7).
    """
    return await _jobs().get_follow_ups(stale_days)


@mcp.tool()
async def get_top_job_fits(min_score: float = 0.7) -> list[dict]:
    """Return saved jobs not yet applied to, sorted by fit score.

    Args:
        min_score: Minimum fit score threshold (0-1, default 0.7).
    """
    return await _jobs().get_top_fits(min_score)


# ---------------------------------------------------------------------------
# Resources (read-only snapshots, good for prompts)
# ---------------------------------------------------------------------------

@mcp.resource("aegis://briefing/latest")
async def briefing_latest_resource() -> str:
    """Latest briefing markdown, suitable for injecting into Claude context."""
    from aegis.db.repository import BriefingRunRepository
    repo = BriefingRunRepository()
    result = await repo.get_latest()
    if result is None:
        return "No briefing available yet. Use the run_briefing tool to generate one."
    return result.get("briefing_markdown", "No markdown stored.")


@mcp.resource("aegis://jobs/summary")
async def jobs_summary_resource() -> str:
    """Plain-text summary of your job pipeline (counts per status)."""
    jobs = await _jobs().list_jobs()
    if not jobs:
        return "No jobs tracked yet. Use add_job to start tracking."

    from collections import Counter
    counts = Counter(j.get("status", "unknown") for j in jobs)
    lines = [f"Total tracked: {len(jobs)}"]
    for status, count in sorted(counts.items()):
        lines.append(f"  {status}: {count}")
    top = await _jobs().get_top_fits(0.7)
    if top:
        lines.append(f"\nTop fits not yet applied ({len(top)}):")
        for j in top[:5]:
            lines.append(f"  - {j['role']} @ {j['company']} (fit: {j['fit_score']:.2f})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
async def daily_briefing_prompt() -> str:
    """Load the latest briefing as a ready-to-use Claude prompt."""
    from aegis.db.repository import BriefingRunRepository
    repo = BriefingRunRepository()
    result = await repo.get_latest()
    if result is None:
        return (
            "No Aegis briefing available. Run run_briefing first, "
            "then call this prompt again."
        )
    md = result.get("briefing_markdown", "")
    return (
        "Here is your Aegis daily briefing. Discuss, ask questions, or act on items.\n\n"
        + md
    )


def main():
    """Entry point: `python -m aegis.mcp_server` or via pyproject scripts."""
    setup_logging()
    from aegis.config import settings
    warnings = settings.check()
    if warnings:
        logger.warning("Aegis config warnings — some features may not work:")
        for w in warnings:
            logger.warning(w)
    logger.info("Starting Aegis MCP server (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
