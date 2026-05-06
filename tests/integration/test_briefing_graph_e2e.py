"""End-to-end test for the briefing graph with mocked sources and LLM."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.briefing.graph import build_briefing_graph
from aegis.briefing.state import BriefingState
from aegis.sources.base import SourceResult
from aegis.llm.gateway import LLMResult


# Mock source results
MOCK_GITHUB = SourceResult(
    source="github",
    ok=True,
    data={"notifications": [{"title": "Review PR #42", "repo": "narenarya3/aegis"}]},
)
MOCK_HN = SourceResult(
    source="hn",
    ok=True,
    data={"stories": [{"title": "Distributed systems in Rust", "score": 300}]},
)
MOCK_JOBS = SourceResult(
    source="jobs",
    ok=True,
    data={"follow_ups": [], "top_fits_not_applied": [], "status_counts": {}, "total": 0},
)

# Mock LLM responses
PRIORITIZE_RESPONSE = json.dumps({
    "items": [
        {"source": "github", "title": "PR review needed", "priority": "high", "reason": "requested", "action": "Review PR #42"},
    ]
})

SYNTHESIZE_RESPONSE = """## Action Required
- Review PR #42 on aegis

## Reading
- Distributed systems in Rust (HN, 300 points)"""

EVALUATE_RESPONSE = json.dumps({
    "relevance": 0.9,
    "actionability": 0.85,
    "conciseness": 0.9,
    "overall": 0.88,
    "feedback": "none",
})


def _make_llm_mock():
    """Create a mock LLMGateway that returns canned responses in order."""
    responses = [PRIORITIZE_RESPONSE, SYNTHESIZE_RESPONSE, EVALUATE_RESPONSE]
    call_idx = 0

    async def mock_call(*, system, user, max_tokens=4096, temperature=0.3):
        nonlocal call_idx
        text = responses[min(call_idx, len(responses) - 1)]
        call_idx += 1
        return LLMResult(text=text, input_tokens=500, output_tokens=200, cost_usd=0.005, model="test")

    return mock_call


@patch("aegis.briefing.nodes.BriefingRunRepository")
@patch("aegis.briefing.nodes.LLMGateway")
@patch("aegis.briefing.nodes.JobsSource")
@patch("aegis.briefing.nodes.HackerNewsSource")
@patch("aegis.briefing.nodes.GitHubSource")
async def test_full_graph_success(
    MockGitHub,
    MockHN,
    MockJobs,
    MockLLMGateway,
    MockRepo,
):
    MockGitHub.return_value.name = "github"
    MockGitHub.return_value.fetch = AsyncMock(return_value=MOCK_GITHUB)
    MockHN.return_value.name = "hn"
    MockHN.return_value.fetch = AsyncMock(return_value=MOCK_HN)
    MockJobs.return_value.name = "jobs"
    MockJobs.return_value.fetch = AsyncMock(return_value=MOCK_JOBS)

    MockLLMGateway.return_value.call = AsyncMock(side_effect=_make_llm_mock())

    mock_repo = MagicMock()
    mock_repo.create_run = AsyncMock()
    mock_repo.update_run = AsyncMock()
    mock_repo.set_latest = AsyncMock()
    MockRepo.return_value = mock_repo

    graph = build_briefing_graph()
    compiled = graph.compile()

    initial_state: BriefingState = {
        "run_id": "",
        "triggered_at": "",
        "trigger_source": "api",
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

    final = await compiled.ainvoke(initial_state)

    assert final["run_id"] != ""
    assert final["briefing_markdown"] is not None
    assert "Action Required" in final["briefing_markdown"]
    assert final["quality_score"] is not None
    assert final["quality_score"] >= 0.7
    assert final["iterations"] >= 1
    assert final["total_cost_usd"] > 0

    assert "github" in final["raw"]
    assert "hn" in final["raw"]
    assert "jobs" in final["raw"]

    mock_repo.create_run.assert_called_once()
    mock_repo.update_run.assert_called_once()
    mock_repo.set_latest.assert_called_once()


@patch("aegis.briefing.nodes.BriefingRunRepository")
@patch("aegis.briefing.nodes.JobsSource")
@patch("aegis.briefing.nodes.HackerNewsSource")
@patch("aegis.briefing.nodes.GitHubSource")
async def test_full_graph_all_sources_fail(
    MockGitHub,
    MockHN,
    MockJobs,
    MockRepo,
):
    """When all sources fail, graph produces degraded output."""
    MockGitHub.return_value.name = "github"
    MockGitHub.return_value.fetch = AsyncMock(return_value=SourceResult(source="github", ok=False, error="401"))
    MockHN.return_value.name = "hn"
    MockHN.return_value.fetch = AsyncMock(return_value=SourceResult(source="hn", ok=False, error="timeout"))
    MockJobs.return_value.name = "jobs"
    MockJobs.return_value.fetch = AsyncMock(return_value=SourceResult(source="jobs", ok=False, error="db down"))

    mock_repo = MagicMock()
    mock_repo.create_run = AsyncMock()
    mock_repo.update_run = AsyncMock()
    mock_repo.set_latest = AsyncMock()
    MockRepo.return_value = mock_repo

    graph = build_briefing_graph()
    compiled = graph.compile()

    initial_state: BriefingState = {
        "run_id": "",
        "triggered_at": "",
        "trigger_source": "api",
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

    final = await compiled.ainvoke(initial_state)

    assert "Degraded" in final["briefing_markdown"]
    assert final["quality_score"] == 0.0
    assert len(final["fetch_errors"]) == 3
