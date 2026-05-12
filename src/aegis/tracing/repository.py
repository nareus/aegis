"""Postgres-backed storage for agent_traces."""

import json
from typing import TYPE_CHECKING
from uuid import UUID

from aegis.db.engine import get_pool

if TYPE_CHECKING:
    from aegis.tracing.spans import SpanRecord


class TraceRepository:
    """CRUD for the agent_traces table."""

    async def insert_span(self, span: "SpanRecord") -> None:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO agent_traces (
                id, run_id, parent_span_id, agent_name, workflow,
                input_payload, started_at
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            """,
            span.id,
            span.run_id,
            span.parent_span_id,
            span.agent_name,
            span.workflow,
            json.dumps(span.input_payload),
            span.started_at,
        )

    async def update_span(self, span: "SpanRecord") -> None:
        pool = await get_pool()
        await pool.execute(
            """
            UPDATE agent_traces
            SET output_payload = $2::jsonb,
                error = $3,
                cost_usd = $4,
                input_tokens = $5,
                output_tokens = $6,
                latency_ms = $7,
                completed_at = $8
            WHERE id = $1
            """,
            span.id,
            json.dumps(span.output_payload) if span.output_payload is not None else None,
            span.error,
            span.cost_usd,
            span.input_tokens,
            span.output_tokens,
            span.latency_ms,
            span.completed_at,
        )

    async def list_recent_runs(self, limit: int = 20) -> list[dict]:
        """Return one summary row per run_id, newest first."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT
                run_id,
                MIN(workflow)              AS workflow,
                MIN(started_at)            AS started_at,
                MAX(completed_at)          AS completed_at,
                COUNT(*)                   AS span_count,
                SUM(cost_usd)              AS total_cost_usd,
                BOOL_OR(error IS NOT NULL) AS has_error
            FROM agent_traces
            GROUP BY run_id
            ORDER BY MIN(started_at) DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]

    async def get_run_tree(self, run_id: UUID) -> list[dict]:
        """Return all spans for a run, ordered for tree reconstruction."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT id, run_id, parent_span_id, agent_name, workflow,
                   input_payload, output_payload, error,
                   cost_usd, input_tokens, output_tokens, latency_ms,
                   started_at, completed_at
            FROM agent_traces
            WHERE run_id = $1
            ORDER BY started_at ASC
            """,
            run_id,
        )
        return [dict(r) for r in rows]
