"""BriefingService -- single entry point for all briefing triggers."""

import time

from loguru import logger

from aegis.briefing.graph import build_briefing_graph
from aegis.briefing.state import BriefingState


class BriefingService:
    """Coordinates briefing runs. All trigger paths (MCP, API, scheduler) go through here."""

    def __init__(self) -> None:
        self._graph = build_briefing_graph()

    async def run(self, trigger_source: str = "api") -> dict:
        """Execute a full briefing run.

        Args:
            trigger_source: "cron", "mcp", or "api"

        Returns:
            Dict with run_id, status, briefing_markdown, quality_score, cost.
        """
        start = time.monotonic()

        initial_state: BriefingState = {
            "run_id": "",
            "triggered_at": "",
            "trigger_source": trigger_source,
            "raw": {},
            "fetch_errors": {},
            "prioritized": None,
            "briefing_markdown": None,
            "quality_score": None,
            "refinement_feedback": "",
            "iterations": 0,
            "total_cost_usd": 0.0,
            "total_latency_ms": 0,
        }

        compiled = self._graph.compile()
        final_state = await compiled.ainvoke(initial_state)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "Briefing run complete: run_id={}, quality={}, cost=${}, elapsed={}ms",
            final_state.get("run_id"),
            final_state.get("quality_score"),
            final_state.get("total_cost_usd"),
            elapsed_ms,
        )

        return {
            "run_id": final_state.get("run_id", ""),
            "status": _derive_status(final_state),
            "briefing_markdown": final_state.get("briefing_markdown"),
            "quality_score": final_state.get("quality_score"),
            "total_cost_usd": final_state.get("total_cost_usd", 0),
            "total_latency_ms": elapsed_ms,
            "sources_ok": [
                k for k, v in final_state.get("raw", {}).items() if v is not None
            ],
            "sources_failed": list(final_state.get("fetch_errors", {}).keys()),
        }


def _derive_status(state: BriefingState) -> str:
    if not state.get("briefing_markdown"):
        return "failed"
    if state.get("quality_score", 0) == 0.0:
        return "degraded"
    return "success"
