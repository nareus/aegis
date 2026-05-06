"""Tests for ResearcherAgent: URL detection, prompt usage, output shape."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import respx

from aegis.agents.researcher import ResearcherAgent, _looks_like_url
from aegis.llm.gateway import LLMGateway, LLMResult
from aegis.tracing.spans import SpanRecord, Tracer


class _FakeRepo:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []

    async def insert_span(self, s: SpanRecord) -> None:
        self.spans.append(s)

    async def update_span(self, s: SpanRecord) -> None:
        pass


def _gateway_returning(text: str) -> LLMGateway:
    gateway = MagicMock(spec=LLMGateway)
    gateway.call = AsyncMock(
        return_value=LLMResult(
            text=text, input_tokens=200, output_tokens=100, cost_usd=0.002, model="t"
        )
    )
    return gateway


SAMPLE_JD = """Senior Backend Engineer at Stripe.
Requirements: Python, distributed systems, PostgreSQL.
Remote OK from US/Singapore. $150k-$200k."""

PARSED = json.dumps({
    "company": "Stripe",
    "role": "Senior Backend Engineer",
    "location": "US/Singapore",
    "remote": True,
    "salary_range": "$150k-$200k",
    "tech_stack": ["python", "distributed-systems", "postgresql"],
    "responsibilities": ["build payments infra"],
    "requirements": ["Python", "distributed systems"],
    "company_context": "Payments platform.",
    "raw_jd_text": SAMPLE_JD,
})


def test_looks_like_url_detection():
    assert _looks_like_url("https://jobs.example.com/123")
    assert _looks_like_url("http://x.io")
    assert not _looks_like_url("Senior Backend Engineer at Stripe...")
    assert not _looks_like_url("ftp://nope.com")


async def test_researcher_with_text_input_skips_fetch():
    gateway = _gateway_returning(PARSED)
    agent = ResearcherAgent(gateway, tracer=Tracer(_FakeRepo()))

    result = await agent.run(run_id=uuid4(), input_payload={"url_or_text": SAMPLE_JD})

    assert result.ok
    assert result.output["company"] == "Stripe"
    assert result.output["fit_score" if False else "tech_stack"] == [
        "python", "distributed-systems", "postgresql"
    ]
    assert "raw_jd_text" in result.output


@respx.mock
async def test_researcher_with_url_fetches_and_parses():
    url = "https://jobs.example.com/role/123"
    respx.get(url).mock(
        return_value=httpx.Response(200, text=SAMPLE_JD)
    )
    gateway = _gateway_returning(PARSED)
    agent = ResearcherAgent(gateway, tracer=Tracer(_FakeRepo()))

    result = await agent.run(run_id=uuid4(), input_payload={"url_or_text": url})

    assert result.ok
    assert result.output["company"] == "Stripe"
    # The LLM was called with the fetched body, not the URL string
    call_kwargs = gateway.call.call_args.kwargs
    assert SAMPLE_JD in call_kwargs["user"]
    assert url not in call_kwargs["user"]


async def test_researcher_returns_error_on_fetch_failure():
    """An unreachable URL should cause the agent to return ok=False (not raise)."""
    bad_url = "http://127.0.0.1:1/no-such-host"
    gateway = _gateway_returning(PARSED)
    agent = ResearcherAgent(gateway, tracer=Tracer(_FakeRepo()))

    result = await agent.run(run_id=uuid4(), input_payload={"url_or_text": bad_url})

    assert result.ok is False
    assert result.error is not None


async def test_researcher_attributes_cost_to_span():
    gateway = _gateway_returning(PARSED)
    repo = _FakeRepo()
    agent = ResearcherAgent(gateway, tracer=Tracer(repo))

    await agent.run(run_id=uuid4(), input_payload={"url_or_text": SAMPLE_JD})

    # Gateway was called with the span argument
    call_kwargs = gateway.call.call_args.kwargs
    assert "span" in call_kwargs
    assert call_kwargs["span"] is repo.spans[0]
