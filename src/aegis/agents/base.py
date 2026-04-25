"""AgentBase: abstract interface with auto-tracing and cost attribution.

Concrete agents implement `_run`. The base class wraps each call in a span,
forwards the span to LLM calls (so cost lands on the right node), captures
exceptions, and returns a uniform `AgentResult`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from loguru import logger

from aegis.llm.gateway import LLMGateway
from aegis.tracing.spans import SpanRecord, Tracer, get_tracer


@dataclass
class AgentResult:
    """Uniform return type for every agent invocation."""

    ok: bool
    span_id: UUID
    cost_usd: float
    latency_ms: int
    output: dict | None = None
    error: str | None = None


class AgentBase(ABC):
    """Shared lifecycle for all agents."""

    name: str = "agent"
    workflow: str = "default"

    def __init__(
        self,
        llm_gateway: LLMGateway,
        tracer: Tracer | None = None,
    ) -> None:
        self._gateway = llm_gateway
        self._tracer = tracer or get_tracer()

    async def run(
        self,
        *,
        run_id: UUID,
        input_payload: dict,
        parent_span_id: UUID | None = None,
    ) -> AgentResult:
        """Execute `_run` inside a span. Never raises for expected agent failures."""
        output: dict | None = None
        error: str | None = None

        async with self._tracer.span(
            run_id=run_id,
            agent_name=self.name,
            workflow=self.workflow,
            input_payload=input_payload,
            parent_span_id=parent_span_id,
        ) as span:
            try:
                with logger.contextualize(run_id=str(run_id), agent_name=self.name):
                    output = await self._run(input_payload, span=span)
                span.output_payload = output
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                span.error = error
                logger.exception("Agent {} failed: {}", self.name, error)

        return AgentResult(
            ok=error is None,
            span_id=span.id,
            cost_usd=span.cost_usd,
            latency_ms=span.latency_ms or 0,
            output=output if error is None else None,
            error=error,
        )

    @abstractmethod
    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        """Concrete agents implement this. Pass `span` to LLM calls for cost attribution."""
