"""Researcher agent: extracts structured data from a JD (text or URL)."""

import httpx
from loguru import logger

from aegis.agents._json import parse_json
from aegis.agents.base import AgentBase
from aegis.llm.prompts import RESEARCHER_SYSTEM
from aegis.tracing.spans import SpanRecord

_FETCH_TIMEOUT_SECONDS = 15.0
_MAX_FETCHED_CHARS = 40_000


class ResearcherAgent(AgentBase):
    """Reads a job posting (text or URL), returns structured fields."""

    name = "researcher"
    workflow = "job_analysis"

    async def _run(self, input_payload: dict, *, span: SpanRecord) -> dict:
        url_or_text: str = input_payload["url_or_text"]
        jd_text = await _resolve_jd_text(url_or_text)

        result = await self._gateway.call(
            system=RESEARCHER_SYSTEM,
            user=f"Parse this job description:\n\n{jd_text}",
            max_tokens=2048,
            span=span,
        )
        parsed = parse_json(result.text)

        # Always include the source text so downstream agents see the original.
        parsed.setdefault("raw_jd_text", jd_text)
        return parsed


async def _resolve_jd_text(url_or_text: str) -> str:
    """If `url_or_text` looks like a URL, fetch and return the body; else return as-is."""
    if not _looks_like_url(url_or_text):
        return url_or_text

    logger.info("Researcher fetching URL: {}", url_or_text)
    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        resp = await client.get(url_or_text, headers={"User-Agent": "Aegis/1.0"})
        resp.raise_for_status()
        text = resp.text
    return text[:_MAX_FETCHED_CHARS]


def _looks_like_url(s: str) -> bool:
    s = s.strip()
    return s.startswith("http://") or s.startswith("https://")
