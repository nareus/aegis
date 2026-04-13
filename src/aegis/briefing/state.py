"""BriefingState TypedDict for LangGraph."""

from typing import TypedDict


class BriefingState(TypedDict):
    run_id: str
    triggered_at: str
    trigger_source: str

    # Raw fetched data, keyed by source name
    raw: dict[str, dict | None]
    fetch_errors: dict[str, str]

    # LLM outputs
    prioritized: dict | None
    briefing_markdown: str | None
    quality_score: float | None
    iterations: int

    # Bookkeeping
    total_cost_usd: float
    total_latency_ms: int
