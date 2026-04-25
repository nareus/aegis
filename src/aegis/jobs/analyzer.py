"""LLM-powered job description parsing and fit scoring."""

import json

from loguru import logger

from aegis.llm.gateway import LLMGateway, LLMResult
from aegis.profile import load_profile

PARSE_JD_SYSTEM = """\
You are a job description parser. Extract structured information from the provided \
job description text or URL content.

Output a JSON object with this exact structure:
{
  "company": "company name",
  "role": "job title",
  "tech_stack": ["python", "kubernetes", ...],
  "salary_range": "100k-150k USD" or null,
  "location": "city, country" or null,
  "remote": true/false/null,
  "requirements_summary": "2-3 sentence summary of key requirements"
}

Return ONLY valid JSON, no markdown fences or extra text."""

FIT_SCORE_SYSTEM = """\
You are a job fit evaluator. Given a candidate's profile and a job description, \
assess how well the candidate fits the role.

Score the fit from 0.0 to 1.0 where:
- 0.9-1.0: Perfect fit, meets all requirements
- 0.7-0.8: Strong fit, meets most requirements
- 0.5-0.6: Moderate fit, meets some requirements but has gaps
- 0.3-0.4: Weak fit, significant gaps
- 0.0-0.2: Poor fit, missing most requirements

Output a JSON object:
{
  "fit_score": 0.0-1.0,
  "matching_skills": ["skill1", "skill2"],
  "missing_skills": ["skill3", "skill4"],
  "notes": "brief assessment of fit and what the candidate should prepare",
  "deal_breaker_found": false,
  "prep_suggestions": ["suggestion1", "suggestion2"]
}

Return ONLY valid JSON, no markdown fences or extra text."""


class JobAnalysisResult:
    """Result of analyzing a job description."""

    def __init__(
        self,
        company: str,
        role: str,
        tech_stack: list[str],
        salary_range: str | None,
        location: str | None,
        remote: bool | None,
        fit_score: float,
        fit_analysis: dict,
    ) -> None:
        self.company = company
        self.role = role
        self.tech_stack = tech_stack
        self.salary_range = salary_range
        self.location = location
        self.remote = remote
        self.fit_score = fit_score
        self.fit_analysis = fit_analysis


class JobAnalyzer:
    """Parses job descriptions and scores fit using LLM."""

    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    async def analyze(self, text: str) -> JobAnalysisResult:
        """Parse a JD and score fit against the user's profile.

        Args:
            text: Raw job description text or content from a URL.

        Returns:
            JobAnalysisResult with parsed data and fit scoring.
        """
        # Step 1: Parse the JD
        parsed = await self._parse_jd(text)

        # Step 2: Score fit against profile
        fit = await self._score_fit(text, parsed)

        result = JobAnalysisResult(
            company=parsed.get("company", "Unknown"),
            role=parsed.get("role", "Unknown"),
            tech_stack=parsed.get("tech_stack", []),
            salary_range=parsed.get("salary_range"),
            location=parsed.get("location"),
            remote=parsed.get("remote"),
            fit_score=fit.get("fit_score", 0.5),
            fit_analysis=fit,
        )

        logger.info(
            "Job analyzed: {} at {} -- fit: {:.1f}",
            result.role,
            result.company,
            result.fit_score,
        )
        return result

    async def _parse_jd(self, text: str) -> dict:
        """Extract structured data from JD text."""
        result = await self._gateway.call(
            system=PARSE_JD_SYSTEM,
            user=f"Parse this job description:\n\n{text}",
            max_tokens=1024,
        )
        return _parse_json(result.text)

    async def _score_fit(self, jd_text: str, parsed: dict) -> dict:
        """Score candidate fit against the job."""
        profile = _build_profile_prompt()
        result = await self._gateway.call(
            system=FIT_SCORE_SYSTEM,
            user=(
                f"Candidate profile:\n{profile}\n\n"
                f"Job description:\n{jd_text}\n\n"
                f"Parsed job data:\n{json.dumps(parsed, indent=2)}"
            ),
            max_tokens=1024,
        )
        return _parse_json(result.text)


def _build_profile_prompt() -> str:
    return load_profile().as_prompt()


def _parse_json(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON response: {}", text[:200])
        return {}
