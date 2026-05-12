"""LLM Gateway -- direct Anthropic SDK wrapper with cost tracking."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anthropic
from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from aegis.config import settings
from aegis.logging import estimate_cost

if TYPE_CHECKING:
    from aegis.tracing.spans import SpanRecord


_RETRYABLE_ANTHROPIC_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


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

    def __init__(
        self,
        budget_usd: float | None = None,
        daily_budget_usd: float | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.aegis_llm_model
        self._budget_usd = budget_usd or settings.aegis_llm_max_cost_usd_per_run
        self._daily_budget_usd = (
            daily_budget_usd
            if daily_budget_usd is not None
            else settings.aegis_llm_max_cost_usd_per_day
        )
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
        await self._check_daily_budget()

        response = await self._create_message(
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(_RETRYABLE_ANTHROPIC_ERRORS),
        before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore[arg-type]
        reraise=True,
    )
    async def _create_message(self, **kwargs):
        return await self._client.messages.create(**kwargs)

    async def _check_daily_budget(self) -> None:
        """Raise BudgetExceededError if aggregate spend in the last 24h exceeds the cap."""
        if self._daily_budget_usd <= 0:
            return  # disabled
        from aegis.db.engine import get_pool

        pool = await get_pool()
        today_usd = await pool.fetchval(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM agent_traces "
            "WHERE started_at > NOW() - INTERVAL '24 hours'"
        )
        if float(today_usd) >= self._daily_budget_usd:
            raise BudgetExceededError(
                f"Daily LLM budget exhausted: "
                f"${float(today_usd):.4f} >= ${self._daily_budget_usd:.4f} (last 24h)"
            )
