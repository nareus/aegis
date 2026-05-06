"""Critic agent: independently re-evaluates the analyst's output."""

import json

from aegis.agents._json import parse_json
from aegis.agents.base import AgentBase
from aegis.llm.prompts import CRITIC_JOB_SYSTEM
from aegis.tracing.spans import SpanRecord


class CriticAgent(AgentBase):
    """Reviews the analyst's job-fit output for common defects."""

    name = "critic"
    workflow = "job_analysis"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        researched: dict = input_payload["researched_job"]
        analysis: dict = input_payload["analysis"]
        profile: str = input_payload["profile"]

        user = (
            f"Candidate profile:\n{profile}\n\n"
            f"Researched job:\n{json.dumps(_summarize(researched), indent=2)}\n\n"
            f"Analyst output to review:\n{json.dumps(analysis, indent=2)}"
        )

        result = await self._gateway.call(
            system=CRITIC_JOB_SYSTEM,
            user=user,
            max_tokens=1024,
            span=span,
        )
        return parse_json(result.text)


def _summarize(researched: dict) -> dict:
    return {k: v for k, v in researched.items() if k != "raw_jd_text"}
