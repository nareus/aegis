"""LangGraph node functions for the daily briefing agent.

Each node is an async function: async def node(state: BriefingState) -> partial state dict.
Nodes are pure-ish: they read from state, do work, and return a partial update.
Side effects (DB writes) are confined to init_run and persist.
"""

import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from loguru import logger

from aegis.briefing.state import BriefingState
from aegis.db.repository import BriefingRunRepository
from aegis.llm.gateway import LLMGateway, BudgetExceededError
from aegis.llm.prompts import (
    PRIORITIZE_SYSTEM,
    PRIORITIZE_USER,
    SYNTHESIZE_SYSTEM,
    SYNTHESIZE_USER,
    EVALUATE_SYSTEM,
    EVALUATE_USER,
)
from aegis.sources.base import SourceResult
from aegis.sources.github import GitHubSource
from aegis.sources.hn import HackerNewsSource
from aegis.sources.leetcode import LeetCodeSource
from aegis.sources.jobs_source import JobsSource
from aegis.sources.leetcode_source import LeetCodeProgressSource


# --- Init ---

async def init_run(state: BriefingState) -> dict:
    """Assign run_id, write initial row to DB."""
    run_id = str(uuid4())
    triggered_at = datetime.now(timezone.utc).isoformat()

    repo = BriefingRunRepository()
    await repo.create_run(
        run_id=__import__("uuid").UUID(run_id),
        triggered_at=triggered_at,
        trigger_source=state.get("trigger_source", "api"),
    )

    logger.bind(run_id=run_id).info("Briefing run started")
    return {
        "run_id": run_id,
        "triggered_at": triggered_at,
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


# --- Fetch nodes (one per source, run in parallel via fan-out) ---

async def fetch_github(state: BriefingState) -> dict:
    return await _fetch_source(state, GitHubSource())


async def fetch_hn(state: BriefingState) -> dict:
    return await _fetch_source(state, HackerNewsSource())


async def fetch_leetcode(state: BriefingState) -> dict:
    return await _fetch_source(state, LeetCodeSource())


async def fetch_jobs(state: BriefingState) -> dict:
    return await _fetch_source(state, JobsSource())


async def fetch_leetcode_progress(state: BriefingState) -> dict:
    return await _fetch_source(state, LeetCodeProgressSource())


async def _fetch_source(state: BriefingState, source) -> dict:
    """Generic fetch wrapper. Returns partial state update for raw/fetch_errors."""
    run_id = state.get("run_id", "")
    start = time.monotonic()

    result: SourceResult = await source.fetch()

    elapsed_ms = int((time.monotonic() - start) * 1000)
    raw = dict(state.get("raw", {}))
    errors = dict(state.get("fetch_errors", {}))

    if result.ok:
        raw[source.name] = result.data
        logger.bind(run_id=run_id).info("{} fetched in {}ms", source.name, elapsed_ms)
    else:
        raw[source.name] = None
        errors[source.name] = result.error or "unknown error"
        logger.bind(run_id=run_id).warning("{} failed: {}", source.name, result.error)

    return {"raw": raw, "fetch_errors": errors}


# --- Check fetches ---

async def check_fetches(state: BriefingState) -> dict:
    """No-op node. Routing logic is in the conditional edge, not here."""
    return {}


def route_after_fetches(state: BriefingState) -> str:
    """Conditional edge: if all sources failed, go degraded; otherwise prioritize."""
    raw = state.get("raw", {})
    any_ok = any(v is not None for v in raw.values())
    return "prioritize" if any_ok else "degraded_output"


# --- LLM nodes ---

async def prioritize(state: BriefingState) -> dict:
    """LLM call: rank and tag items by relevance."""
    gateway = LLMGateway()
    raw_data = json.dumps(state.get("raw", {}), indent=2, default=str)

    try:
        result = await gateway.call(
            system=PRIORITIZE_SYSTEM,
            user=PRIORITIZE_USER.format(raw_data=raw_data),
            max_tokens=2048,
        )
        prioritized = _parse_json_safe(result.text)
        cost = result.cost_usd
    except BudgetExceededError:
        logger.warning("Budget exceeded during prioritize")
        return {"prioritized": None}
    except Exception as e:
        logger.warning("Prioritize failed: {}", str(e))
        return {"prioritized": None}

    return {
        "prioritized": prioritized,
        "total_cost_usd": state.get("total_cost_usd", 0) + cost,
    }


async def synthesize(state: BriefingState) -> dict:
    """LLM call: write the final markdown briefing."""
    gateway = LLMGateway()
    prioritized_data = json.dumps(state.get("prioritized", {}), indent=2, default=str)
    feedback = state.get("refinement_feedback", "")
    feedback_block = f"Previous feedback to address:\n{feedback}" if feedback else ""

    try:
        result = await gateway.call(
            system=SYNTHESIZE_SYSTEM,
            user=SYNTHESIZE_USER.format(
                prioritized_data=prioritized_data,
                refinement_feedback=feedback_block,
            ),
            max_tokens=2048,
        )
        cost = result.cost_usd
    except BudgetExceededError:
        logger.warning("Budget exceeded during synthesize")
        return {}
    except Exception as e:
        logger.warning("Synthesize failed: {}", str(e))
        return {}

    return {
        "briefing_markdown": result.text,
        "iterations": state.get("iterations", 0) + 1,
        "total_cost_usd": state.get("total_cost_usd", 0) + cost,
    }


async def self_evaluate(state: BriefingState) -> dict:
    """LLM call: score the briefing quality 0-1."""
    gateway = LLMGateway()
    raw_data = json.dumps(state.get("raw", {}), indent=2, default=str)
    briefing = state.get("briefing_markdown", "")

    try:
        result = await gateway.call(
            system=EVALUATE_SYSTEM,
            user=EVALUATE_USER.format(raw_data=raw_data, briefing_markdown=briefing),
            max_tokens=512,
        )
        evaluation = _parse_json_safe(result.text)
        score = evaluation.get("overall", 0.7)
        feedback = evaluation.get("feedback", "")
        cost = result.cost_usd
    except (BudgetExceededError, Exception):
        score = 0.7
        feedback = ""
        cost = 0.0

    return {
        "quality_score": score,
        "refinement_feedback": feedback,
        "total_cost_usd": state.get("total_cost_usd", 0) + cost,
    }


async def maybe_refine(state: BriefingState) -> dict:
    """No-op node. Routing logic is in the conditional edge."""
    return {}


def route_after_evaluate(state: BriefingState) -> str:
    """Conditional: refine if score < 0.7 and iterations < 2."""
    score = state.get("quality_score", 0.7)
    iterations = state.get("iterations", 0)
    if score < 0.7 and iterations < 2:
        return "synthesize"
    return "persist"


# --- Degraded output ---

async def degraded_output(state: BriefingState) -> dict:
    """Emit a minimal briefing when all sources failed."""
    errors = state.get("fetch_errors", {})
    lines = ["## Briefing (Degraded)", ""]
    lines.append("All data sources failed during this run:")
    for source, error in errors.items():
        lines.append(f"- **{source}**: {error}")
    lines.append("")
    lines.append("Please check your configuration and try again.")

    return {
        "briefing_markdown": "\n".join(lines),
        "quality_score": 0.0,
        "iterations": 1,
    }


# --- Persist ---

async def persist(state: BriefingState) -> dict:
    """Write final state to DB and update latest pointer."""
    import uuid

    repo = BriefingRunRepository()
    run_id = uuid.UUID(state["run_id"])

    raw = state.get("raw", {})
    sources_ok = [k for k, v in raw.items() if v is not None]
    sources_failed = state.get("fetch_errors", {})

    status = "success"
    if state.get("quality_score", 0) == 0.0:
        status = "degraded"
    if not state.get("briefing_markdown"):
        status = "failed"

    elapsed = int((time.monotonic()) * 1000)  # approximate

    await repo.update_run(
        run_id,
        status=status,
        briefing_md=state.get("briefing_markdown"),
        quality_score=state.get("quality_score"),
        iterations=state.get("iterations", 1),
        sources_ok=sources_ok,
        sources_failed=sources_failed,
        total_cost_usd=state.get("total_cost_usd", 0),
        total_latency_ms=elapsed,
    )

    if status in ("success", "degraded"):
        await repo.set_latest(run_id)

    logger.bind(run_id=state["run_id"]).info(
        "Briefing persisted: status={}, quality={}, cost=${}",
        status,
        state.get("quality_score"),
        state.get("total_cost_usd", 0),
    )
    return {}


# --- Helpers ---

def _parse_json_safe(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
