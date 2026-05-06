"""Tests for CriticAgent: verdict shape and prompt isolation."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from aegis.agents.critic import CriticAgent
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
        return_value=LLMResult(text=text, input_tokens=200, output_tokens=80, cost_usd=0.001, model="t")
    )
    return g


RESEARCHED = {"company": "Acme", "role": "SWE", "raw_jd_text": "verbose body"}
ANALYSIS = {"fit_score": 0.9, "matching_skills": ["python"]}

APPROVE = json.dumps({"verdict": "approve", "issues": [], "confidence": 0.9})
REVISE = json.dumps({
    "verdict": "revise",
    "issues": [
        {"type": "score-inflation", "description": "0.9 too high", "severity": "high"}
    ],
    "confidence": 0.85,
})


async def test_critic_returns_approve_verdict():
    agent = CriticAgent(_gateway(APPROVE), tracer=Tracer(_FakeRepo()))

    result = await agent.run(
        run_id=uuid4(),
        input_payload={"researched_job": RESEARCHED, "analysis": ANALYSIS, "profile": "p"},
    )

    assert result.ok
    assert result.output["verdict"] == "approve"
    assert result.output["issues"] == []


async def test_critic_returns_revise_verdict_with_issues():
    agent = CriticAgent(_gateway(REVISE), tracer=Tracer(_FakeRepo()))

    result = await agent.run(
        run_id=uuid4(),
        input_payload={"researched_job": RESEARCHED, "analysis": ANALYSIS, "profile": "p"},
    )

    assert result.ok
    assert result.output["verdict"] == "revise"
    assert result.output["issues"][0]["severity"] == "high"


async def test_critic_omits_raw_jd_from_prompt():
    g = _gateway(APPROVE)
    agent = CriticAgent(g, tracer=Tracer(_FakeRepo()))

    await agent.run(
        run_id=uuid4(),
        input_payload={"researched_job": RESEARCHED, "analysis": ANALYSIS, "profile": "p"},
    )

    user_prompt = g.call.call_args.kwargs["user"]
    assert "verbose body" not in user_prompt
    assert "Acme" in user_prompt
