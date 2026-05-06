"""Data access layer for job applications."""

import json
from datetime import datetime, timezone
from uuid import UUID

from loguru import logger

from aegis.db.engine import get_pool


class JobApplicationRepository:
    """Repository for the job_applications table."""

    async def create(
        self,
        *,
        company: str,
        role: str,
        url: str | None = None,
        source_text: str | None = None,
        status: str = "saved",
        fit_score: float | None = None,
        fit_analysis: dict | None = None,
        tech_stack: list[str] | None = None,
        salary_range: str | None = None,
        location: str | None = None,
        remote: bool | None = None,
        notes: str | None = None,
    ) -> UUID:
        """Insert a new job application. Returns the generated ID."""
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO job_applications
                (company, role, url, source_text, status, fit_score, fit_analysis,
                 tech_stack, salary_range, location, remote, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12)
            RETURNING id
            """,
            company,
            role,
            url,
            source_text,
            status,
            fit_score,
            json.dumps(fit_analysis) if fit_analysis else None,
            tech_stack or [],
            salary_range,
            location,
            remote,
            notes,
        )
        logger.info("Created job application: {} at {}", role, company)
        return row["id"]

    async def create_with_analysis(
        self,
        *,
        company: str,
        role: str,
        url: str | None,
        source_text: str | None,
        tech_stack: list[str],
        location: str | None,
        remote: bool | None,
        salary_range: str | None,
        fit_score: float | None,
        fit_analysis: dict,
        critic_feedback: dict | None,
        refinement_count: int,
        analysis_run_id: UUID,
    ) -> UUID:
        """Insert a job alongside its multi-agent analysis trace pointer."""
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO job_applications
                (company, role, url, source_text, status, fit_score, fit_analysis,
                 tech_stack, salary_range, location, remote,
                 critic_feedback, refinement_count, analysis_run_id)
            VALUES ($1, $2, $3, $4, 'saved', $5, $6::jsonb,
                    $7, $8, $9, $10,
                    $11::jsonb, $12, $13)
            RETURNING id
            """,
            company,
            role,
            url,
            source_text,
            fit_score,
            json.dumps(fit_analysis),
            tech_stack,
            salary_range,
            location,
            remote,
            json.dumps(critic_feedback) if critic_feedback else None,
            refinement_count,
            analysis_run_id,
        )
        logger.info(
            "Created job with analysis: {} at {} (fit={}, refinements={}, run_id={})",
            role, company, fit_score, refinement_count, analysis_run_id,
        )
        return row["id"]

    async def get(self, job_id: UUID) -> dict | None:
        """Fetch a job application by ID."""
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM job_applications WHERE id = $1", job_id
        )
        return _row_to_dict(row) if row else None

    async def list_all(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        """List job applications, optionally filtered by status."""
        pool = await get_pool()
        if status:
            rows = await pool.fetch(
                "SELECT * FROM job_applications WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                status,
                limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM job_applications ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [_row_to_dict(r) for r in rows]

    async def update_status(
        self,
        job_id: UUID,
        status: str,
        notes: str | None = None,
    ) -> bool:
        """Update the status of a job application. Returns True if found."""
        pool = await get_pool()
        now = datetime.now(timezone.utc)
        result = await pool.execute(
            """
            UPDATE job_applications
            SET status = $2, notes = COALESCE($3, notes),
                last_activity = $4, updated_at = $4,
                applied_date = CASE WHEN $2 = 'applied' AND applied_date IS NULL THEN $4 ELSE applied_date END
            WHERE id = $1
            """,
            job_id,
            status,
            notes,
            now,
        )
        return result == "UPDATE 1"

    async def get_follow_ups(self, stale_days: int = 7) -> list[dict]:
        """Get applications with no activity in the last N days."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM job_applications
            WHERE status NOT IN ('rejected', 'withdrawn', 'offer')
              AND last_activity < NOW() - INTERVAL '1 day' * $1
            ORDER BY last_activity ASC
            """,
            stale_days,
        )
        return [_row_to_dict(r) for r in rows]

    async def get_by_fit_score(self, min_score: float = 0.7, limit: int = 10) -> list[dict]:
        """Get top-fit jobs that haven't been applied to yet."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM job_applications
            WHERE fit_score >= $1 AND status = 'saved'
            ORDER BY fit_score DESC
            LIMIT $2
            """,
            min_score,
            limit,
        )
        return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> dict:
    """Convert an asyncpg Record to a dict, JSON-decoding JSONB string fields."""
    d = dict(row)
    for key in ("fit_analysis", "critic_feedback"):
        if d.get(key) and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d
