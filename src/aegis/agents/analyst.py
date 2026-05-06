"""Analyst agent: scores fit between researched job and candidate profile."""

import json

from aegis.agents._json import parse_json
from aegis.agents.base import AgentBase
from aegis.llm.prompts import ANALYST_SYSTEM
from aegis.tracing.spans import SpanRecord


class AnalystAgent(AgentBase):
    """Compares researcher output against the profile and produces a fit_score."""

    name = "analyst"
    workflow = "job_analysis"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        researched: dict = input_payload["researched_job"]
        profile: str = input_payload["profile"]
        feedback: dict | None = input_payload.get("previous_critic_feedback")

        feedback_section = ""
        if feedback:
            feedback_section = (
                "\n\nThe previous version of this analysis was reviewed and the "
                "critic returned the following issues. Address each one and "
                "adjust your analysis accordingly:\n"
                f"{json.dumps(feedback, indent=2)}\n"
            )

        user = (
            f"Candidate profile:\n{profile}\n\n"
            f"Researched job:\n{json.dumps(_summarize_for_prompt(researched), indent=2)}"
            f"{feedback_section}"
        )

        result = await self._gateway.call(
            system=ANALYST_SYSTEM,
            user=user,
            max_tokens=1500,
            span=span,
        )
        return parse_json(result.text)


def _summarize_for_prompt(researched: dict) -> dict:
    """Drop verbose `raw_jd_text` to keep the analyst prompt focused."""
    return {k: v for k, v in researched.items() if k != "raw_jd_text"}
