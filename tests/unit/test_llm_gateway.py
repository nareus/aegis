"""Tests for LLM gateway."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aegis.llm.gateway import LLMGateway, LLMResult, BudgetExceededError


def _mock_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Create a mock Anthropic message response."""
    content_block = MagicMock()
    content_block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    response.model = "claude-sonnet-4-5-20250514"
    return response


@patch("aegis.llm.gateway.anthropic.AsyncAnthropic")
async def test_call_returns_result(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_mock_response("Hello world", input_tokens=200, output_tokens=100)
    )
    mock_anthropic_cls.return_value = mock_client

    gateway = LLMGateway(budget_usd=1.0)
    result = await gateway.call(system="You are helpful.", user="Say hello.")

    assert isinstance(result, LLMResult)
    assert result.text == "Hello world"
    assert result.input_tokens == 200
    assert result.output_tokens == 100
    assert result.cost_usd > 0
    assert gateway.total_spent > 0


@patch("aegis.llm.gateway.anthropic.AsyncAnthropic")
async def test_cost_tracking_accumulates(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_mock_response("Response", input_tokens=1000, output_tokens=500)
    )
    mock_anthropic_cls.return_value = mock_client

    gateway = LLMGateway(budget_usd=10.0)

    await gateway.call(system="sys", user="msg1")
    spent_after_first = gateway.total_spent

    await gateway.call(system="sys", user="msg2")
    assert gateway.total_spent > spent_after_first
    assert gateway.total_input_tokens == 2000
    assert gateway.total_output_tokens == 1000


@patch("aegis.llm.gateway.anthropic.AsyncAnthropic")
async def test_budget_exceeded_raises(mock_anthropic_cls):
    mock_client = MagicMock()
    # Each call costs: (1M/1M) * 3.0 + (500K/1M) * 15.0 = 3.0 + 7.5 = $10.50
    mock_client.messages.create = AsyncMock(
        return_value=_mock_response("Expensive", input_tokens=1_000_000, output_tokens=500_000)
    )
    mock_anthropic_cls.return_value = mock_client

    gateway = LLMGateway(budget_usd=0.50)

    # First call succeeds but exhausts budget
    await gateway.call(system="sys", user="msg")
    assert gateway.total_spent > 0.50

    # Second call should raise
    with pytest.raises(BudgetExceededError):
        await gateway.call(system="sys", user="msg2")


@patch("aegis.llm.gateway.anthropic.AsyncAnthropic")
async def test_call_passes_parameters(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_mock_response("OK")
    )
    mock_anthropic_cls.return_value = mock_client

    gateway = LLMGateway(budget_usd=1.0)
    await gateway.call(
        system="Be concise.",
        user="Summarize this.",
        max_tokens=2048,
        temperature=0.5,
    )

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == "Be concise."
    assert call_kwargs["messages"] == [{"role": "user", "content": "Summarize this."}]
    assert call_kwargs["max_tokens"] == 2048
    assert call_kwargs["temperature"] == 0.5
