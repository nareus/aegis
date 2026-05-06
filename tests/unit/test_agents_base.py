"""Tests for AgentBase: span emission, success/error paths, cost attribution."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from aegis.agents.base import AgentBase, AgentResult
from aegis.llm.gateway import LLMGateway, LLMResult
from aegis.tracing.spans import SpanRecord, Tracer


class _FakeRepo:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []
        self.updates: list[SpanRecord] = []

    async def insert_span(self, span: SpanRecord) -> None:
        self.spans.append(span)

    async def update_span(self, span: SpanRecord) -> None:
        self.updates.append(span)


class _EchoAgent(AgentBase):
    name = "echo"
    workflow = "test"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        span.cost_usd = 0.002
        span.input_tokens = 50
        span.output_tokens = 25
        return {"echo": input_payload.get("msg", "")}


class _BoomAgent(AgentBase):
    name = "boom"
    workflow = "test"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        raise RuntimeError("kaboom")


def _make_gateway() -> LLMGateway:
    gateway = MagicMock(spec=LLMGateway)
    gateway.call = AsyncMock()
    return gateway


async def test_agent_run_success_returns_ok_result():
    repo = _FakeRepo()
    tracer = Tracer(repository=repo)
    agent = _EchoAgent(_make_gateway(), tracer=tracer)
    run_id = uuid4()

    result = await agent.run(run_id=run_id, input_payload={"msg": "hello"})

    assert isinstance(result, AgentResult)
    assert result.ok is True
    assert result.output == {"echo": "hello"}
    assert result.error is None
    assert result.cost_usd == 0.002
    assert result.latency_ms >= 0
    assert isinstance(result.span_id, UUID)


async def test_agent_run_failure_returns_error_result_without_raising():
    repo = _FakeRepo()
    tracer = Tracer(repository=repo)
    agent = _BoomAgent(_make_gateway(), tracer=tracer)

    result = await agent.run(run_id=uuid4(), input_payload={})

    assert result.ok is False
    assert result.output is None
    assert "RuntimeError: kaboom" in result.error
    assert len(repo.updates) == 1
    assert "RuntimeError: kaboom" in repo.updates[0].error


async def test_agent_run_persists_input_and_output_in_span():
    repo = _FakeRepo()
    tracer = Tracer(repository=repo)
    agent = _EchoAgent(_make_gateway(), tracer=tracer)

    await agent.run(run_id=uuid4(), input_payload={"msg": "ping"})

    assert repo.spans[0].input_payload == {"msg": "ping"}
    assert repo.updates[0].output_payload == {"echo": "ping"}


async def test_agent_run_propagates_parent_span_id():
    repo = _FakeRepo()
    tracer = Tracer(repository=repo)
    agent = _EchoAgent(_make_gateway(), tracer=tracer)
    parent = uuid4()

    await agent.run(run_id=uuid4(), input_payload={}, parent_span_id=parent)

    assert repo.spans[0].parent_span_id == parent


async def test_gateway_call_attributes_cost_to_span():
    """When LLMGateway.call receives a span, it should accumulate cost/tokens on it."""
    from unittest.mock import patch

    with patch("aegis.llm.gateway.anthropic.AsyncAnthropic") as mock_cls:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ok")]
        mock_response.usage = MagicMock(input_tokens=200, output_tokens=100)
        mock_response.model = "claude-test"
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        gateway = LLMGateway(budget_usd=10.0)
        span = SpanRecord(
            run_id=uuid4(), agent_name="x", workflow="w", input_payload={}
        )

        await gateway.call(system="s", user="u", span=span)
        await gateway.call(system="s", user="u", span=span)

        assert span.input_tokens == 400
        assert span.output_tokens == 200
        assert span.cost_usd > 0
