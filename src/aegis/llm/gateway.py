"""LLM Gateway -- direct Anthropic SDK wrapper with cost tracking."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anthropic
from loguru import logger

from aegis.config import settings
from aegis.logging import estimate_cost

if TYPE_CHECKING:
    from aegis.tracing.spans import SpanRecord


@dataclass
class LLMResult:
    """Result of an LLM call."""

    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str


class BudgetExceededError(Exception):
    """Raised when a run would exceed its cost budget."""


class LLMGateway:
    """Thin wrapper around the Anthropic SDK with cost tracking and budget enforcement."""

    def __init__(self, budget_usd: float | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.aegis_llm_model
        self._budget_usd = budget_usd or settings.aegis_llm_max_cost_usd_per_run
        self._spent_usd: float = 0.0
        self._calls: list[LLMResult] = []

    @property
    def total_spent(self) -> float:
        return self._spent_usd

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self._calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self._calls)

    async def call(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        span: "SpanRecord | None" = None,
    ) -> LLMResult:
        """Make a single LLM call. Raises BudgetExceededError if budget would be exceeded.

        If `span` is provided, attributes cost and tokens to it (additive — multiple
        calls within one span accumulate).
        """
        if self._spent_usd >= self._budget_usd:
            raise BudgetExceededError(
                f"Budget exhausted: ${self._spent_usd:.4f} >= ${self._budget_usd:.4f}"
            )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        text = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_cost(input_tokens, output_tokens)

        result = LLMResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=response.model,
        )

        self._spent_usd += cost
        self._calls.append(result)

        if span is not None:
            span.cost_usd += cost
            span.input_tokens += input_tokens
            span.output_tokens += output_tokens

        logger.info(
            "LLM call: {} input, {} output tokens, ${:.4f} (total: ${:.4f}/{:.4f})",
            input_tokens,
            output_tokens,
            cost,
            self._spent_usd,
            self._budget_usd,
        )

        if self._spent_usd >= self._budget_usd:
            logger.warning("Budget exhausted after this call")

        return result
