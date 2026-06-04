"""Briefing agents — each LLM step in the briefing pipeline as an AgentBase.

Each agent owns one LLM call; AgentBase handles span creation, cost +
token attribution, error capture, and persistence to `agent_traces`.
Graph wiring lives in briefing/graph.py.
"""

import json

from aegis.agents._json import parse_json
from aegis.agents.base import AgentBase
from aegis.llm.prompts import (
    EVALUATE_SYSTEM,
    EVALUATE_USER,
    PRIORITIZE_SYSTEM,
    PRIORITIZE_USER,
    SYNTHESIZE_SYSTEM,
    SYNTHESIZE_USER,
)
from aegis.tracing.spans import SpanRecord


class PrioritizerAgent(AgentBase):
    """Rank and tag fetched items by relevance against the candidate profile."""

    name = "prioritizer"
    workflow = "briefing"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        raw_data = json.dumps(input_payload["raw"], indent=2, default=str)
        result = await self._gateway.call(
            system=PRIORITIZE_SYSTEM,
            user=PRIORITIZE_USER.format(raw_data=raw_data),
            max_tokens=2048,
            span=span,
        )
        return parse_json(result.text)


class SynthesizerAgent(AgentBase):
    """Compose the briefing markdown from prioritized items + optional feedback."""

    name = "synthesizer"
    workflow = "briefing"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        prioritized = input_payload.get("prioritized") or {}
        feedback = input_payload.get("refinement_feedback", "")
        feedback_block = (
            f"Previous feedback to address:\n{feedback}" if feedback else ""
        )

        result = await self._gateway.call(
            system=SYNTHESIZE_SYSTEM,
            user=SYNTHESIZE_USER.format(
                prioritized_data=json.dumps(prioritized, indent=2, default=str),
                refinement_feedback=feedback_block,
            ),
            max_tokens=2048,
            span=span,
        )
        return {"markdown": result.text}


class EvaluatorAgent(AgentBase):
    """Score the briefing 0-1 and emit feedback for the next refinement pass."""

    name = "evaluator"
    workflow = "briefing"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        raw_data = json.dumps(input_payload["raw"], indent=2, default=str)
        briefing = input_payload["briefing_markdown"]
        result = await self._gateway.call(
            system=EVALUATE_SYSTEM,
            user=EVALUATE_USER.format(
                raw_data=raw_data, briefing_markdown=briefing
            ),
            max_tokens=512,
            span=span,
        )
        return parse_json(result.text)
