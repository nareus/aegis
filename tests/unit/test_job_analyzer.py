"""Tests for job analyzer (LLM-powered JD parsing and fit scoring)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.jobs.analyzer import JobAnalyzer, _parse_json, _build_profile_prompt
from aegis.llm.gateway import LLMGateway, LLMResult


def _make_gateway_mock(*responses: str) -> LLMGateway:
    """Create a mock gateway that returns predetermined responses."""
    gateway = MagicMock(spec=LLMGateway)
    call_results = [
        LLMResult(text=r, input_tokens=100, output_tokens=50, cost_usd=0.001, model="test")
        for r in responses
    ]
    gateway.call = AsyncMock(side_effect=call_results)
    return gateway


SAMPLE_JD = """
Senior Backend Engineer at Stripe

We're looking for a backend engineer to work on our payments infrastructure.

Requirements:
- 3+ years Python or Go experience
- Experience with distributed systems
- PostgreSQL and Redis experience
- Kubernetes is a plus
- Remote OK (US/Singapore)

Salary: $150k-$200k
"""

PARSED_RESPONSE = json.dumps({
    "company": "Stripe",
    "role": "Senior Backend Engineer",
    "tech_stack": ["python", "golang", "distributed-systems", "postgresql", "redis", "kubernetes"],
    "salary_range": "$150k-$200k",
    "location": "US/Singapore",
    "remote": True,
    "requirements_summary": "Backend engineer for payments infrastructure, needs Python/Go, distributed systems, and database experience."
})

FIT_RESPONSE = json.dumps({
    "fit_score": 0.85,
    "matching_skills": ["python", "golang", "distributed-systems", "postgresql", "redis", "kubernetes"],
    "missing_skills": ["payments-domain"],
    "notes": "Strong technical fit. Candidate has all required skills. Missing payments domain experience but transferable skills are strong.",
    "deal_breaker_found": False,
    "prep_suggestions": ["Study payment processing systems", "Review Stripe's engineering blog"]
})


async def test_analyze_returns_result():
    gateway = _make_gateway_mock(PARSED_RESPONSE, FIT_RESPONSE)
    analyzer = JobAnalyzer(gateway)

    result = await analyzer.analyze(SAMPLE_JD)

    assert result.company == "Stripe"
    assert result.role == "Senior Backend Engineer"
    assert result.fit_score == 0.85
    assert "python" in result.tech_stack
    assert result.remote is True
    assert result.salary_range == "$150k-$200k"
    assert "matching_skills" in result.fit_analysis
    assert "missing_skills" in result.fit_analysis


async def test_analyze_makes_two_llm_calls():
    gateway = _make_gateway_mock(PARSED_RESPONSE, FIT_RESPONSE)
    analyzer = JobAnalyzer(gateway)

    await analyzer.analyze(SAMPLE_JD)

    assert gateway.call.call_count == 2


async def test_analyze_handles_malformed_llm_response():
    gateway = _make_gateway_mock("not json at all", "{}")
    analyzer = JobAnalyzer(gateway)

    result = await analyzer.analyze(SAMPLE_JD)

    # Should not crash, returns defaults
    assert result.company == "Unknown"
    assert result.role == "Unknown"
    assert result.fit_score == 0.5  # default when missing


def test_parse_json_strips_markdown_fences():
    text = '```json\n{"key": "value"}\n```'
    assert _parse_json(text) == {"key": "value"}


def test_parse_json_handles_plain_json():
    text = '{"key": "value"}'
    assert _parse_json(text) == {"key": "value"}


def test_parse_json_handles_invalid():
    assert _parse_json("not json") == {}


def test_build_profile_prompt():
    prompt = _build_profile_prompt()
    assert "python" in prompt
    assert "backend-engineer" in prompt
    assert "singapore" in prompt
