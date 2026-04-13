"""Data access layer for briefing runs."""

from uuid import UUID

from loguru import logger

from aegis.db.engine import get_pool


class BriefingRunRepository:
    """Repository for briefing_runs and briefing_latest tables."""

    async def create_run(
        self,
        run_id: UUID,
        triggered_at: str,
        trigger_source: str,
    ) -> None:
        """Insert a new run with status 'running'."""
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO briefing_runs (run_id, triggered_at, trigger_source, status)
            VALUES ($1, $2::timestamptz, $3, 'running')
            """,
            run_id,
            triggered_at,
            trigger_source,
        )
        logger.info("Created briefing run", run_id=str(run_id))

    async def update_run(
        self,
        run_id: UUID,
        *,
        status: str,
        briefing_md: str | None = None,
        quality_score: float | None = None,
        iterations: int = 1,
        sources_ok: list[str] | None = None,
        sources_failed: dict | None = None,
        total_cost_usd: float = 0,
        total_latency_ms: int | None = None,
    ) -> None:
        """Update a run with final results."""
        pool = await get_pool()
        await pool.execute(
            """
            UPDATE briefing_runs
            SET status = $2, briefing_md = $3, quality_score = $4,
                iterations = $5, sources_ok = $6, sources_failed = $7::jsonb,
                total_cost_usd = $8, total_latency_ms = $9, updated_at = NOW()
            WHERE run_id = $1
            """,
            run_id,
            status,
            briefing_md,
            quality_score,
            iterations,
            sources_ok or [],
            _json_str(sources_failed or {}),
            total_cost_usd,
            total_latency_ms,
        )

    async def set_latest(self, run_id: UUID) -> None:
        """Update the briefing_latest pointer to this run."""
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO briefing_latest (id, run_id, updated_at)
            VALUES (1, $1, NOW())
            ON CONFLICT (id) DO UPDATE SET run_id = $1, updated_at = NOW()
            """,
            run_id,
        )

    async def get_run(self, run_id: UUID) -> dict | None:
        """Fetch a specific run by ID."""
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM briefing_runs WHERE run_id = $1", run_id
        )
        return dict(row) if row else None

    async def get_latest(self) -> dict | None:
        """Fetch the latest successful briefing run."""
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT br.* FROM briefing_runs br
            JOIN briefing_latest bl ON br.run_id = bl.run_id
            """
        )
        return dict(row) if row else None

    async def list_recent(self, limit: int = 10) -> list[dict]:
        """List recent runs ordered by triggered_at descending."""
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT * FROM briefing_runs ORDER BY triggered_at DESC LIMIT $1",
            limit,
        )
        return [dict(r) for r in rows]


def _json_str(obj: dict) -> str:
    """Convert dict to JSON string for asyncpg JSONB parameter."""
    import json
    return json.dumps(obj)
