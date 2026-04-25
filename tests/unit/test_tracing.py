"""Tests for the tracing module: span lifecycle, repository persistence, viewer."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from aegis.tracing.spans import SpanRecord, Tracer
from aegis.tracing.viewer import render_trace_html


class _FakeRepo:
    """In-memory stand-in for TraceRepository."""

    def __init__(self) -> None:
        self.spans: dict[UUID, SpanRecord] = {}
        self.insert_calls: list[SpanRecord] = []
        self.update_calls: list[SpanRecord] = []

    async def insert_span(self, span: SpanRecord) -> None:
        self.spans[span.id] = span
        self.insert_calls.append(span)

    async def update_span(self, span: SpanRecord) -> None:
        self.update_calls.append(span)

    async def get_run_tree(self, run_id: UUID) -> list[dict]:
        return [_to_dict(s) for s in self.spans.values() if s.run_id == run_id]


def _to_dict(span: SpanRecord) -> dict:
    return {
        "id": span.id,
        "run_id": span.run_id,
        "parent_span_id": span.parent_span_id,
        "agent_name": span.agent_name,
        "workflow": span.workflow,
        "input_payload": span.input_payload,
        "output_payload": span.output_payload,
        "error": span.error,
        "cost_usd": span.cost_usd,
        "input_tokens": span.input_tokens,
        "output_tokens": span.output_tokens,
        "latency_ms": span.latency_ms,
        "started_at": span.started_at,
        "completed_at": span.completed_at,
    }


async def test_span_lifecycle_persists_start_and_end():
    repo = _FakeRepo()
    tracer = Tracer(repository=repo)
    run_id = uuid4()

    async with tracer.span(
        run_id=run_id,
        agent_name="test_agent",
        workflow="testing",
        input_payload={"q": "hi"},
    ) as span:
        span.output_payload = {"answer": "yo"}
        span.cost_usd = 0.01
        span.input_tokens = 100
        span.output_tokens = 50

    assert len(repo.insert_calls) == 1
    assert len(repo.update_calls) == 1
    final = repo.update_calls[0]
    assert final.output_payload == {"answer": "yo"}
    assert final.cost_usd == 0.01
    assert final.error is None
    assert final.completed_at is not None
    assert final.latency_ms is not None and final.latency_ms >= 0


async def test_span_records_exception_and_reraises():
    repo = _FakeRepo()
    tracer = Tracer(repository=repo)

    with pytest.raises(ValueError):
        async with tracer.span(
            run_id=uuid4(),
            agent_name="boom",
            workflow="testing",
            input_payload={},
        ):
            raise ValueError("explode")

    assert len(repo.update_calls) == 1
    assert "ValueError: explode" in repo.update_calls[0].error


async def test_parent_span_linkage():
    repo = _FakeRepo()
    tracer = Tracer(repository=repo)
    run_id = uuid4()

    async with tracer.span(
        run_id=run_id, agent_name="root", workflow="w", input_payload={}
    ) as root:
        async with tracer.span(
            run_id=run_id,
            agent_name="child",
            workflow="w",
            input_payload={},
            parent_span_id=root.id,
        ) as child:
            assert child.parent_span_id == root.id

    parents = {s.id: s.parent_span_id for s in repo.insert_calls}
    assert parents[root.id] is None
    assert parents[child.id] == root.id


def test_render_trace_html_with_spans():
    run_id = uuid4()
    root_id = uuid4()
    child_id = uuid4()
    spans = [
        {
            "id": root_id, "run_id": run_id, "parent_span_id": None,
            "agent_name": "researcher", "workflow": "job_analysis",
            "input_payload": {"url": "x"}, "output_payload": {"company": "Acme"},
            "error": None, "cost_usd": 0.005, "input_tokens": 100, "output_tokens": 50,
            "latency_ms": 1200,
            "started_at": datetime.now(timezone.utc), "completed_at": datetime.now(timezone.utc),
        },
        {
            "id": child_id, "run_id": run_id, "parent_span_id": root_id,
            "agent_name": "llm_call", "workflow": "job_analysis",
            "input_payload": {"prompt": "..."}, "output_payload": None,
            "error": "timeout", "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
            "latency_ms": 500,
            "started_at": datetime.now(timezone.utc), "completed_at": datetime.now(timezone.utc),
        },
    ]

    html = render_trace_html(run_id, spans)
    assert "researcher" in html
    assert "Acme" in html
    assert "llm_call" in html
    assert "timeout" in html
    assert str(run_id) in html
    assert "$0.0050" in html


def test_render_trace_html_empty():
    run_id = uuid4()
    html = render_trace_html(run_id, [])
    assert "No spans recorded" in html
    assert str(run_id) in html
