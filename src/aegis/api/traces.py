"""Trace viewer endpoints: HTML page and raw JSON."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from aegis.tracing.repository import TraceRepository
from aegis.tracing.viewer import render_trace_html

router = APIRouter(tags=["traces"])


@router.get("/trace/{run_id}", response_class=HTMLResponse)
async def get_trace_html(run_id: UUID) -> HTMLResponse:
    spans = await TraceRepository().get_run_tree(run_id)
    if not spans:
        raise HTTPException(status_code=404, detail="No trace for that run_id")
    return HTMLResponse(content=render_trace_html(run_id, spans))


@router.get("/trace/{run_id}/json")
async def get_trace_json(run_id: UUID) -> dict:
    spans = await TraceRepository().get_run_tree(run_id)
    if not spans:
        raise HTTPException(status_code=404, detail="No trace for that run_id")
    return {"run_id": str(run_id), "spans": [_serialize_span(s) for s in spans]}


def _serialize_span(span: dict) -> dict:
    """Convert UUIDs/datetimes/Decimals to JSON-friendly types."""
    return {
        "id": str(span["id"]),
        "parent_span_id": str(span["parent_span_id"]) if span["parent_span_id"] else None,
        "agent_name": span["agent_name"],
        "workflow": span["workflow"],
        "input_payload": span["input_payload"],
        "output_payload": span["output_payload"],
        "error": span["error"],
        "cost_usd": float(span["cost_usd"]) if span["cost_usd"] is not None else None,
        "input_tokens": span["input_tokens"],
        "output_tokens": span["output_tokens"],
        "latency_ms": span["latency_ms"],
        "started_at": span["started_at"].isoformat() if span["started_at"] else None,
        "completed_at": span["completed_at"].isoformat() if span["completed_at"] else None,
    }
