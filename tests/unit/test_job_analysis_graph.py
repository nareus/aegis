"""End-to-end tests for the job_analysis LangGraph (mocked LLM, in-memory tracer)."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from aegis.agents.analyst import AnalystAgent
from aegis.agents.critic import CriticAgent
from aegis.agents.researcher import ResearcherAgent
from aegis.config import settings
from aegis.llm.gateway import LLMGateway, LLMResult
from aegis.tracing.spans import SpanRecord, Tracer
from aegis.workflows.job_analysis.graph import build_job_analysis_graph
from aegis.workflows.job_analysis.state import JobAnalysisState


class _MemRepo:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []

    async def insert_span(self, s: SpanRecord) -> None:
        self.spans.append(s)

    async def update_span(self, s: SpanRecord) -> None:
        pass


RESEARCHED = {
    "company": "Stripe", "role": "Backend Eng",
    "tech_stack": ["python"], "requirements": ["python"],
    "raw_jd_text": "JD body",
}
ANALYSIS = {
    "fit_score": 0.8, "reasoning": "good fit",
    "matching_skills": ["python"], "gap_skills": [],
    "critical_gaps": [], "deal_breakers_present": [],
    "recommendation": "apply", "notes": None,
}


def _scripted_gateway(*responses: str) -> LLMGateway:
    """Returns LLMResult for each scripted response, mutating span like the real gateway."""
    gateway = MagicMock(spec=LLMGateway)
    results = [
        LLMResult(text=r, input_tokens=200, output_tokens=80, cost_usd=0.002, model="t")
        for r in responses
    ]
    idx = 0

    async def call(*, system, user, max_tokens=4096, temperature=0.3, span=None):
        nonlocal idx
        result = results[min(idx, len(results) - 1)]
        idx += 1
        if span is not None:
            span.cost_usd += result.cost_usd
            span.input_tokens += result.input_tokens
            span.output_tokens += result.output_tokens
        return result

    gateway.call = AsyncMock(side_effect=call)
    return gateway


def _build_graph_with(gateway: LLMGateway, repo: _MemRepo):
    tracer = Tracer(repo)
    return build_job_analysis_graph(
        ResearcherAgent(gateway, tracer=tracer),
        AnalystAgent(gateway, tracer=tracer),
        CriticAgent(gateway, tracer=tracer),
    ).compile()


def _initial_state(run_id: UUID) -> JobAnalysisState:
    return {
        "run_id": run_id,
        "input": {"url_or_text": "Senior Backend at Stripe..."},
        "profile": "skills: python",
        "researched": None, "analysis": None, "critic_feedback": None,
        "refinement_count": 0, "final_analysis": None,
        "error": None, "total_cost_usd": 0.0,
    }


async def test_graph_happy_path_no_refinement():
    """Critic approves on first pass → 3 spans, refinement_count=0."""
    gateway = _scripted_gateway(
        json.dumps(RESEARCHED),
        json.dumps(ANALYSIS),
        json.dumps({"verdict": "approve", "issues": [], "confidence": 0.9}),
    )
    repo = _MemRepo()
    graph = _build_graph_with(gateway, repo)

    final = await graph.ainvoke(_initial_state(uuid4()))

    assert final["final_analysis"]["fit_score"] == 0.8
    assert final["refinement_count"] == 0
    assert final["error"] is None
    # researcher + analyst + critic = 3 spans
    assert len(repo.spans) == 3
    assert [s.agent_name for s in repo.spans] == ["researcher", "analyst", "critic"]


async def test_graph_refines_once_when_critic_revises():
    """First critic asks for revision, second approves → 5 spans, refinement_count=1."""
    revised_analysis = {**ANALYSIS, "fit_score": 0.65}
    gateway = _scripted_gateway(
        json.dumps(RESEARCHED),
        json.dumps(ANALYSIS),
        json.dumps({"verdict": "revise", "issues": [
            {"type": "score-inflation", "description": "Too high", "severity": "high"}
        ], "confidence": 0.8}),
        json.dumps(revised_analysis),
        json.dumps({"verdict": "approve", "issues": [], "confidence": 0.9}),
    )
    repo = _MemRepo()
    graph = _build_graph_with(gateway, repo)

    final = await graph.ainvoke(_initial_state(uuid4()))

    assert final["final_analysis"]["fit_score"] == 0.65
    assert final["refinement_count"] == 1
    assert len(repo.spans) == 5
    assert [s.agent_name for s in repo.spans] == [
        "researcher", "analyst", "critic", "analyst", "critic"
    ]


async def test_graph_caps_refinements_at_max(monkeypatch):
    """Critic always says revise → loop should stop at AEGIS_MAX_REFINEMENTS."""
    monkeypatch.setattr(settings, "aegis_max_refinements", 2)

    gateway = _scripted_gateway(
        json.dumps(RESEARCHED),
        json.dumps(ANALYSIS),
        json.dumps({"verdict": "revise", "issues": [
            {"type": "x", "description": "y", "severity": "high"}
        ], "confidence": 0.5}),
        json.dumps(ANALYSIS),
        json.dumps({"verdict": "revise", "issues": [
            {"type": "x", "description": "y", "severity": "high"}
        ], "confidence": 0.5}),
        json.dumps(ANALYSIS),
        json.dumps({"verdict": "revise", "issues": [
            {"type": "x", "description": "y", "severity": "high"}
        ], "confidence": 0.5}),
    )
    repo = _MemRepo()
    graph = _build_graph_with(gateway, repo)

    final = await graph.ainvoke(_initial_state(uuid4()))

    assert final["refinement_count"] == 2
    assert final["final_analysis"] is not None  # still persisted
    # 1 researcher + 3 analyst + 3 critic
    assert len(repo.spans) == 7


async def test_graph_records_total_cost_across_agents():
    gateway = _scripted_gateway(
        json.dumps(RESEARCHED),
        json.dumps(ANALYSIS),
        json.dumps({"verdict": "approve", "issues": [], "confidence": 0.9}),
    )
    repo = _MemRepo()
    graph = _build_graph_with(gateway, repo)

    final = await graph.ainvoke(_initial_state(uuid4()))

    # 3 calls × $0.002 = $0.006
    assert final["total_cost_usd"] > 0.005
