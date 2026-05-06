"""Tests for AnalystAgent: profile injection, refinement-feedback handling."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from aegis.agents.analyst import AnalystAgent
from aegis.llm.gateway import LLMGateway, LLMResult
from aegis.tracing.spans import SpanRecord, Tracer


class _FakeRepo:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []

    async def insert_span(self, s: SpanRecord) -> None:
        self.spans.append(s)

    async def update_span(self, s: SpanRecord) -> None:
        pass


def _gateway(text: str) -> LLMGateway:
    g = MagicMock(spec=LLMGateway)
    g.call = AsyncMock(
        return_value=LLMResult(text=text, input_tokens=300, output_tokens=120, cost_usd=0.003, model="t")
    )
    return g


RESEARCHED = {
    "company": "Stripe",
    "role": "Senior Backend Engineer",
    "tech_stack": ["python", "postgresql"],
    "requirements": ["Python", "PostgreSQL"],
    "raw_jd_text": "long body...",
}

ANALYSIS = json.dumps({
    "fit_score": 0.82,
    "reasoning": "Strong overlap on python and postgresql.",
    "matching_skills": ["python", "postgresql"],
    "gap_skills": [],
    "critical_gaps": [],
    "deal_breakers_present": [],
    "recommendation": "apply",
    "notes": None,
})


async def test_analyst_returns_parsed_output():
    g = _gateway(ANALYSIS)
    agent = AnalystAgent(g, tracer=Tracer(_FakeRepo()))

    result = await agent.run(
        run_id=uuid4(),
        input_payload={"researched_job": RESEARCHED, "profile": "skills: python"},
    )

    assert result.ok
    assert result.output["fit_score"] == 0.82
    assert result.output["recommendation"] == "apply"


async def test_analyst_strips_raw_jd_from_prompt():
    """Researcher's `raw_jd_text` is verbose -- analyst prompt should not include it."""
    g = _gateway(ANALYSIS)
    agent = AnalystAgent(g, tracer=Tracer(_FakeRepo()))

    await agent.run(
        run_id=uuid4(),
        input_payload={"researched_job": RESEARCHED, "profile": "p"},
    )

    user_prompt = g.call.call_args.kwargs["user"]
    assert "long body..." not in user_prompt
    assert "Stripe" in user_prompt


async def test_analyst_includes_critic_feedback_when_present():
    g = _gateway(ANALYSIS)
    agent = AnalystAgent(g, tracer=Tracer(_FakeRepo()))
    feedback = {
        "verdict": "revise",
        "issues": [{"type": "score-inflation", "description": "Too high", "severity": "high"}],
    }

    await agent.run(
        run_id=uuid4(),
        input_payload={
            "researched_job": RESEARCHED,
            "profile": "p",
            "previous_critic_feedback": feedback,
        },
    )

    user_prompt = g.call.call_args.kwargs["user"]
    assert "score-inflation" in user_prompt
    assert "revise" in user_prompt


async def test_analyst_omits_feedback_section_when_absent():
    g = _gateway(ANALYSIS)
    agent = AnalystAgent(g, tracer=Tracer(_FakeRepo()))

    await agent.run(
        run_id=uuid4(),
        input_payload={"researched_job": RESEARCHED, "profile": "p"},
    )

    user_prompt = g.call.call_args.kwargs["user"]
    assert "previous version" not in user_prompt.lower()
