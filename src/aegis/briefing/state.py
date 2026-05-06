"""BriefingState TypedDict for LangGraph with custom reducers for parallel fan-out."""

from typing import Annotated, TypedDict


def merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges dicts. Used for raw data and fetch_errors
    so parallel fetch nodes can each contribute their key."""
    merged = dict(left)
    merged.update(right)
    return merged


class BriefingState(TypedDict):
    run_id: str
    triggered_at: str
    trigger_source: str                  # "mcp" | "api"

    # Annotated with merge_dicts so parallel fetch nodes can write concurrently
    raw: Annotated[dict[str, dict | None], merge_dicts]
    fetch_errors: Annotated[dict[str, str], merge_dicts]

    # LLM outputs
    prioritized: dict | None
    briefing_markdown: str | None
    quality_score: float | None
    refinement_feedback: str
    iterations: int

    # Bookkeeping
    total_cost_usd: float
    total_latency_ms: int
