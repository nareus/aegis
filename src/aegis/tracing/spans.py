"""Span emission for agent traces.

A `SpanRecord` represents a single traced operation. The `Tracer.span` async
context manager handles start/complete/failure persistence; the LLM gateway
mutates the record in-place to attach cost and token counts.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID, uuid4

from aegis.tracing.repository import TraceRepository


@dataclass
class SpanRecord:
    """A single traced agent or LLM operation."""

    run_id: UUID
    agent_name: str
    workflow: str
    input_payload: dict
    parent_span_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    output_payload: dict | None = None
    error: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class Tracer:
    """Persists span lifecycle events to Postgres."""

    def __init__(self, repository: TraceRepository | None = None) -> None:
        self._repo = repository or TraceRepository()

    @asynccontextmanager
    async def span(
        self,
        *,
        run_id: UUID,
        agent_name: str,
        workflow: str,
        input_payload: dict,
        parent_span_id: UUID | None = None,
    ) -> AsyncIterator[SpanRecord]:
        """Create a span, persist it, and ensure completion is recorded.

        The yielded `SpanRecord` is mutable: callers (agents, gateways) write
        `output_payload`, `cost_usd`, token counts, etc. before exiting the
        block. Exceptions are recorded as `error` and re-raised.
        """
        record = SpanRecord(
            run_id=run_id,
            agent_name=agent_name,
            workflow=workflow,
            input_payload=input_payload,
            parent_span_id=parent_span_id,
        )
        await self._repo.insert_span(record)
        try:
            yield record
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record.completed_at = datetime.now(timezone.utc)
            record.latency_ms = int(
                (record.completed_at - record.started_at).total_seconds() * 1000
            )
            await self._repo.update_span(record)


_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    """Process-wide tracer singleton."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def reset_tracer() -> None:
    """Test helper: clear the singleton so the next get_tracer() rebuilds it."""
    global _tracer
    _tracer = None
