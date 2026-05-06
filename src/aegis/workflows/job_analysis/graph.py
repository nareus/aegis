"""LangGraph state machine: Researcher → Analyst → Critic → (refine or persist).

Node functions are factories that close over agent instances; the public
`build_job_analysis_graph` returns a compiled graph ready for `ainvoke`.
"""

from typing import Callable

from langgraph.graph import END, START, StateGraph
from loguru import logger

from aegis.agents.analyst import AnalystAgent
from aegis.agents.critic import CriticAgent
from aegis.agents.researcher import ResearcherAgent
from aegis.config import settings
from aegis.workflows.job_analysis.state import JobAnalysisState


def build_job_analysis_graph(
    researcher: ResearcherAgent,
    analyst: AnalystAgent,
    critic: CriticAgent,
) -> StateGraph:
    """Wire the four nodes into a compilable LangGraph."""
    graph = StateGraph(JobAnalysisState)

    graph.add_node("researcher", _researcher_node(researcher))
    graph.add_node("analyst", _analyst_node(analyst))
    graph.add_node("critic", _critic_node(critic))
    graph.add_node("finalize", _finalize_node)

    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_edge("analyst", "critic")

    graph.add_conditional_edges(
        "critic",
        _route_after_critic,
        {"analyst": "analyst", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph


def _researcher_node(agent: ResearcherAgent) -> Callable:
    async def node(state: JobAnalysisState) -> dict:
        result = await agent.run(
            run_id=state["run_id"],
            input_payload={"url_or_text": state["input"]["url_or_text"]},
        )
        if not result.ok:
            return {
                "error": f"researcher failed: {result.error}",
                "researched": None,
                "total_cost_usd": state.get("total_cost_usd", 0.0) + result.cost_usd,
            }
        return {
            "researched": result.output,
            "total_cost_usd": state.get("total_cost_usd", 0.0) + result.cost_usd,
        }

    return node


def _analyst_node(agent: AnalystAgent) -> Callable:
    async def node(state: JobAnalysisState) -> dict:
        if state.get("error"):
            return {}  # short-circuit; finalize will degrade gracefully

        feedback = state.get("critic_feedback")
        # If we've already been here once (feedback exists), this run is a refinement.
        new_refinement_count = state.get("refinement_count", 0)
        if feedback is not None:
            new_refinement_count += 1

        result = await agent.run(
            run_id=state["run_id"],
            input_payload={
                "researched_job": state["researched"],
                "profile": state["profile"],
                "previous_critic_feedback": feedback,
            },
        )
        if not result.ok:
            return {
                "error": f"analyst failed: {result.error}",
                "total_cost_usd": state.get("total_cost_usd", 0.0) + result.cost_usd,
            }
        return {
            "analysis": result.output,
            "refinement_count": new_refinement_count,
            "total_cost_usd": state.get("total_cost_usd", 0.0) + result.cost_usd,
        }

    return node


def _critic_node(agent: CriticAgent) -> Callable:
    async def node(state: JobAnalysisState) -> dict:
        if state.get("error") or state.get("analysis") is None:
            return {}

        result = await agent.run(
            run_id=state["run_id"],
            input_payload={
                "researched_job": state["researched"],
                "analysis": state["analysis"],
                "profile": state["profile"],
            },
        )
        # Critic failure should not block persistence -- just record empty feedback.
        feedback = result.output if result.ok else {"verdict": "approve", "issues": []}
        return {
            "critic_feedback": feedback,
            "total_cost_usd": state.get("total_cost_usd", 0.0) + result.cost_usd,
        }

    return node


def _route_after_critic(state: JobAnalysisState) -> str:
    """Approve → finalize. Revise + budget left → loop back to analyst. Else finalize."""
    if state.get("error") or state.get("analysis") is None:
        return "finalize"

    feedback = state.get("critic_feedback") or {}
    verdict = feedback.get("verdict", "approve")
    refinement_count = state.get("refinement_count", 0)

    if verdict == "revise" and refinement_count < settings.aegis_max_refinements:
        logger.info(
            "Critic requested revision (round {} of {})",
            refinement_count + 1,
            settings.aegis_max_refinements,
        )
        return "analyst"
    return "finalize"


async def _finalize_node(state: JobAnalysisState) -> dict:
    """Promote the latest analysis to `final_analysis`."""
    if state.get("error"):
        return {"final_analysis": None}

    feedback = state.get("critic_feedback") or {}
    if (
        feedback.get("verdict") == "revise"
        and state.get("refinement_count", 0) >= settings.aegis_max_refinements
    ):
        logger.warning(
            "Refinement cap reached; persisting analyst output with critic concerns"
        )

    return {"final_analysis": state.get("analysis")}
