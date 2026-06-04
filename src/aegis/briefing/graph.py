"""Build the LangGraph briefing graph."""

import uuid
from typing import Callable

from langgraph.graph import StateGraph, START, END
from loguru import logger

from aegis.briefing.agents import (
    EvaluatorAgent,
    PrioritizerAgent,
    SynthesizerAgent,
)
from aegis.briefing.nodes import (
    check_fetches,
    degraded_output,
    fetch_github,
    fetch_hn,
    fetch_jobs,
    init_run,
    maybe_refine,
    persist,
    route_after_evaluate,
    route_after_fetches,
)
from aegis.briefing.state import BriefingState


def build_briefing_graph(
    prioritizer: PrioritizerAgent,
    synthesizer: SynthesizerAgent,
    evaluator: EvaluatorAgent,
) -> StateGraph:
    """Construct the briefing graph.

    Graph topology:
        init_run
           |
           +-- fetch_github
           +-- fetch_hn
           +-- fetch_jobs
           |
        check_fetches
          /         \\
     all fail      >=1 ok
         |            |
    degraded      prioritize    (PrioritizerAgent — span recorded)
         |            |
         |        synthesize    (SynthesizerAgent — span recorded)
         |            |
         |        self_evaluate (EvaluatorAgent — span recorded)
         |            |
         |        maybe_refine -> synthesize (if score < 0.7 and iterations < 2)
         |            |
         +--- persist ----> END

    LLM nodes are built by the three factories below; each wraps an
    AgentBase invocation and translates AgentResult into a state delta,
    accumulating cost regardless of success.
    """
    graph = StateGraph(BriefingState)

    # Static nodes (no LLM, no spans needed)
    graph.add_node("init_run", init_run)
    graph.add_node("fetch_github", fetch_github)
    graph.add_node("fetch_hn", fetch_hn)
    graph.add_node("fetch_jobs", fetch_jobs)
    graph.add_node("check_fetches", check_fetches)
    graph.add_node("maybe_refine", maybe_refine)
    graph.add_node("degraded_output", degraded_output)
    graph.add_node("persist", persist)

    # Agent-backed LLM nodes (spans recorded by AgentBase)
    graph.add_node("prioritize", _prioritize_node(prioritizer))
    graph.add_node("synthesize", _synthesize_node(synthesizer))
    graph.add_node("self_evaluate", _self_evaluate_node(evaluator))

    # Entry
    graph.add_edge(START, "init_run")

    # Fan-out: init_run -> all fetch nodes in parallel
    graph.add_edge("init_run", "fetch_github")
    graph.add_edge("init_run", "fetch_hn")
    graph.add_edge("init_run", "fetch_jobs")

    # Fan-in: all fetch nodes -> check_fetches
    graph.add_edge("fetch_github", "check_fetches")
    graph.add_edge("fetch_hn", "check_fetches")
    graph.add_edge("fetch_jobs", "check_fetches")

    # Conditional: check_fetches -> prioritize or degraded_output
    graph.add_conditional_edges(
        "check_fetches",
        route_after_fetches,
        {"prioritize": "prioritize", "degraded_output": "degraded_output"},
    )

    # Main path
    graph.add_edge("prioritize", "synthesize")
    graph.add_edge("synthesize", "self_evaluate")
    graph.add_edge("self_evaluate", "maybe_refine")

    # Conditional: maybe_refine -> synthesize (loop) or persist
    graph.add_conditional_edges(
        "maybe_refine",
        route_after_evaluate,
        {"synthesize": "synthesize", "persist": "persist"},
    )

    # Degraded path -> persist
    graph.add_edge("degraded_output", "persist")

    # End
    graph.add_edge("persist", END)

    return graph


# ─── Node factories: wrap AgentBase.run, translate AgentResult → state delta ──


def _prioritize_node(agent: PrioritizerAgent) -> Callable:
    async def node(state: BriefingState) -> dict:
        result = await agent.run(
            run_id=uuid.UUID(state["run_id"]),
            input_payload={"raw": state.get("raw", {})},
        )
        accrued = state.get("total_cost_usd", 0.0) + result.cost_usd
        if not result.ok:
            logger.warning("Prioritize failed: {}", result.error)
            return {"prioritized": None, "total_cost_usd": accrued}
        return {"prioritized": result.output, "total_cost_usd": accrued}

    return node


def _synthesize_node(agent: SynthesizerAgent) -> Callable:
    async def node(state: BriefingState) -> dict:
        result = await agent.run(
            run_id=uuid.UUID(state["run_id"]),
            input_payload={
                "prioritized": state.get("prioritized"),
                "refinement_feedback": state.get("refinement_feedback", ""),
            },
        )
        accrued = state.get("total_cost_usd", 0.0) + result.cost_usd
        if not result.ok:
            logger.warning("Synthesize failed: {}", result.error)
            return {"total_cost_usd": accrued}
        markdown = (result.output or {}).get("markdown")
        return {
            "briefing_markdown": markdown,
            "iterations": state.get("iterations", 0) + 1,
            "total_cost_usd": accrued,
        }

    return node


def _self_evaluate_node(agent: EvaluatorAgent) -> Callable:
    async def node(state: BriefingState) -> dict:
        result = await agent.run(
            run_id=uuid.UUID(state["run_id"]),
            input_payload={
                "raw": state.get("raw", {}),
                "briefing_markdown": state.get("briefing_markdown", ""),
            },
        )
        accrued = state.get("total_cost_usd", 0.0) + result.cost_usd
        if not result.ok:
            logger.warning("Self-evaluate failed: {}", result.error)
            return {
                "quality_score": 0.7,
                "refinement_feedback": "",
                "total_cost_usd": accrued,
            }
        out = result.output or {}
        return {
            "quality_score": out.get("overall", 0.7),
            "refinement_feedback": out.get("feedback", ""),
            "total_cost_usd": accrued,
        }

    return node
