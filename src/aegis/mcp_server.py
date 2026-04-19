"""MCP server -- tools/resources/prompts wired to Aegis services."""

from fastmcp import FastMCP
from loguru import logger

from aegis.briefing.service import BriefingService
from aegis.interview.service import InterviewService
from aegis.jobs.service import JobService
from aegis.leetcode.service import LeetCodeService
from aegis.logging import setup_logging

mcp = FastMCP("Aegis")

_briefing_service: BriefingService | None = None
_job_service: JobService | None = None
_lc_service: LeetCodeService | None = None
_interview_service: InterviewService | None = None


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


def _lc() -> LeetCodeService:
    global _lc_service
    if _lc_service is None:
        _lc_service = LeetCodeService()
    return _lc_service


def _interview() -> InterviewService:
    global _interview_service
    if _interview_service is None:
        _interview_service = InterviewService()
    return _interview_service


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
# LeetCode tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def log_leetcode_problem(
    title: str,
    title_slug: str,
    difficulty: str,
    patterns: list[str],
    solved: bool = True,
    url: str = "",
    time_complexity: str = "",
    notes: str = "",
) -> dict:
    """Manually log a LeetCode problem attempt.

    Args:
        title:           Problem title (e.g. "Two Sum").
        title_slug:      URL slug (e.g. "two-sum").
        difficulty:      Easy | Medium | Hard.
        patterns:        List of pattern slugs (e.g. ["arrays", "hash-table"]).
        solved:          Whether you solved it (default True).
        url:             LeetCode problem URL (optional).
        time_complexity: e.g. "O(n)" (optional).
        notes:           Any personal notes (optional).

    Returns:
        id, title, solved.
    """
    return await _lc().log_problem(
        title=title,
        title_slug=title_slug,
        difficulty=difficulty,
        patterns=patterns,
        solved=solved,
        url=url or None,
        time_complexity=time_complexity or None,
        notes=notes or None,
    )


@mcp.tool()
async def get_leetcode_progress() -> dict:
    """Return your full LeetCode progress summary.

    Includes: total solved, streak, per-pattern coverage, weak patterns,
    and breakdown by difficulty.
    """
    return await _lc().get_progress()


@mcp.tool()
async def suggest_next_problem() -> dict:
    """Use AI to suggest the single best next LeetCode problem to practice.

    Based on your pattern gaps and what's commonly asked in backend/AI interviews.

    Returns:
        title, title_slug, difficulty, patterns, reason, url.
    """
    return await _lc().suggest_next()


@mcp.tool()
async def get_weak_patterns() -> list[str]:
    """Return LeetCode patterns where you have fewer than 3 solved problems.

    Ordered weakest first.
    """
    return await _lc().get_weak_patterns()


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


@mcp.resource("aegis://leetcode/progress")
async def leetcode_progress_resource() -> str:
    """Plain-text LeetCode progress snapshot."""
    progress = await _lc().get_progress()
    lines = [
        f"Total solved: {progress['total_solved']}",
        f"Current streak: {progress['streak_days']} days",
        "",
        "By difficulty:",
    ]
    for diff, count in progress["by_difficulty"].items():
        lines.append(f"  {diff}: {count}")
    lines.append("")
    lines.append("Weakest patterns (under 3 solved):")
    for p in progress["weak_patterns"][:8]:
        covered = progress["pattern_coverage"].get(p, {})
        lines.append(f"  {p}: {covered.get('solved', 0)} solved")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interview prep tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def mock_system_design(company: str = "", topic: str = "", job_id: str = "") -> dict:
    """Generate a system design interview question and start a session.

    Args:
        company: Target company name (e.g. "Stripe", "Datadog"). Leave empty for generic.
        topic:   Specific focus area (e.g. "rate limiting", "event streaming").
        job_id:  UUID of a tracked job to link this session to (optional).

    Returns:
        session_id, question, company.
        Save the session_id to submit your answer with evaluate_answer.
    """
    return await _interview().mock_system_design(
        company=company or None,
        topic=topic or None,
        job_id=job_id or None,
    )


@mcp.tool()
async def mock_behavioral(company: str = "", job_id: str = "") -> dict:
    """Generate a behavioural interview question (STAR framework).

    Args:
        company: Target company name to tailor the question to their values.
        job_id:  UUID of a tracked job to link this session to (optional).

    Returns:
        session_id, question, company.
    """
    return await _interview().mock_behavioral(
        company=company or None,
        job_id=job_id or None,
    )


@mcp.tool()
async def evaluate_answer(session_id: str, answer: str) -> dict:
    """Submit your answer to a mock interview question for LLM evaluation.

    Args:
        session_id: The session_id returned by mock_system_design or mock_behavioral.
        answer:     Your answer text (as detailed as you like).

    Returns:
        score (0-1), strengths, gaps, weak_areas, suggested_improvements, model_answer_hint.
    """
    return await _interview().evaluate_answer(session_id, answer)


@mcp.tool()
async def get_interview_readiness(company: str = "") -> dict:
    """Get your interview readiness score based on past prep sessions.

    Args:
        company: Filter to sessions for a specific company (optional).

    Returns:
        overall_score, breakdown by type, top_weak_areas, readiness_level, summary, key_gaps.
    """
    return await _interview().get_readiness(company=company or None)


@mcp.tool()
async def list_interview_sessions(
    company: str = "",
    session_type: str = "",
    limit: int = 20,
) -> list[dict]:
    """List past interview prep sessions.

    Args:
        company:      Filter by company name (optional).
        session_type: "system-design" or "behavioral" (optional).
        limit:        Max results (default 20).
    """
    return await _interview().list_sessions(
        company=company or None,
        session_type=session_type or None,
        limit=limit,
    )


@mcp.resource("aegis://interview/readiness")
async def interview_readiness_resource() -> str:
    """Plain-text interview readiness snapshot across all sessions."""
    readiness = await _interview().get_readiness()
    level = readiness.get("readiness_level", "unknown")
    score = readiness.get("overall_score")
    score_str = f"{score:.2f}" if score is not None else "no data"
    lines = [
        f"Readiness level: {level}",
        f"Overall score: {score_str}",
        "",
        readiness.get("summary", "No sessions yet."),
    ]
    gaps = readiness.get("key_gaps", [])
    if gaps:
        lines.append("\nKey gaps:")
        for g in gaps:
            lines.append(f"  - {g}")
    next_action = readiness.get("recommended_next")
    if next_action:
        lines.append(f"\nRecommended next: {next_action}")
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
