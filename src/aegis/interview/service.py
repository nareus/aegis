"""Interview Prep Agent -- mock questions, answer evaluation, readiness scoring."""

import json
from uuid import UUID

from loguru import logger

from aegis.config import settings
from aegis.db.interview_repository import InterviewRepository
from aegis.llm.gateway import LLMGateway

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_PROFILE = """\
Candidate profile:
- Skills: {skills}
- Target roles: {roles}
- Experience: {years} years
- Preferred locations: {locations}"""

_SYSTEM_DESIGN_SYSTEM = """\
You are a senior engineering interviewer at a top tech company. Generate a challenging but \
realistic system design interview question.

{profile}

Guidelines:
- Tailor difficulty and domain to the candidate's level and target roles
- If a company is specified, make the question relevant to their domain
- If a topic is specified, center the question around it
- Keep the question concise (2-4 sentences) but rich enough to explore for 45 minutes
- End with: "Walk me through your design."

Output ONLY the question text, no preamble."""

_BEHAVIORAL_SYSTEM = """\
You are a senior engineering interviewer. Generate a behavioural interview question \
using the STAR framework (Situation, Task, Action, Result).

{profile}

Guidelines:
- Questions should probe engineering leadership, collaboration, conflict resolution, \
  or handling technical ambiguity
- If a company is specified, tailor to their known culture/values
- Keep it to 1-2 sentences

Output ONLY the question text, no preamble."""

_EVALUATE_SYSTEM = """\
You are an expert technical interviewer. Evaluate the candidate's answer to an interview question.

{profile}

Scoring rubric:
- 0.9-1.0: Exceptional -- thorough, structured, shows depth and leadership
- 0.7-0.89: Strong -- covers key points, minor gaps
- 0.5-0.69: Adequate -- hits basics but lacks depth or structure
- 0.3-0.49: Weak -- significant gaps, unclear thinking
- 0.0-0.29: Insufficient -- misses the point or very incomplete

Output a JSON object:
{{
  "score": 0.0-1.0,
  "strengths": ["what was done well"],
  "gaps": ["what was missing or weak"],
  "weak_areas": ["skills/topics to improve, e.g. 'distributed-systems', 'leadership'"],
  "suggested_improvements": "1-2 sentences of targeted advice",
  "model_answer_hint": "key points a strong answer would cover"
}}

Return ONLY valid JSON."""

_READINESS_SYSTEM = """\
You are a career coach reviewing an engineer's interview readiness.

{profile}

Based on the session history provided, give a holistic readiness assessment.

Output a JSON object:
{{
  "readiness_level": "not-ready" | "developing" | "ready" | "strong",
  "summary": "2-3 sentence honest assessment",
  "key_gaps": ["top 3 gaps to address before the interview"],
  "recommended_next": "single most important thing to do next"
}}

Return ONLY valid JSON."""


def _profile_str() -> str:
    return _PROFILE.format(
        skills=", ".join(settings.skills_list),
        roles=", ".join(settings.target_roles_list),
        years=settings.aegis_profile_experience_years,
        locations=", ".join(settings.preferred_locations_list),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class InterviewService:
    """High-level service for interview prep sessions."""

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._repo = InterviewRepository()
        self._gateway = gateway

    def _gw(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = LLMGateway()
        return self._gateway

    async def mock_system_design(
        self,
        company: str | None = None,
        topic: str | None = None,
        job_id: str | None = None,
    ) -> dict:
        """Generate a system design question and persist the session.

        Args:
            company:  Target company name (optional, makes question more relevant).
            topic:    Specific topic to focus on (e.g. "rate limiting", "caching").
            job_id:   UUID of related job application (optional).

        Returns:
            session_id, question, company.
        """
        user_parts = []
        if company:
            user_parts.append(f"Company: {company}")
        if topic:
            user_parts.append(f"Topic: {topic}")
        user_msg = "\n".join(user_parts) if user_parts else "General system design question."

        result = await self._gw().call(
            system=_SYSTEM_DESIGN_SYSTEM.format(profile=_profile_str()),
            user=user_msg,
            max_tokens=512,
            temperature=0.8,
        )
        question = result.text.strip()

        jid = UUID(job_id) if job_id else None
        session_id = await self._repo.create_session(
            session_type="system-design",
            question=question,
            job_id=jid,
            company=company,
        )

        logger.info("System design question generated: session={}", session_id)
        return {
            "session_id": str(session_id),
            "session_type": "system-design",
            "question": question,
            "company": company,
        }

    async def mock_behavioral(
        self,
        company: str | None = None,
        job_id: str | None = None,
    ) -> dict:
        """Generate a behavioural interview question.

        Args:
            company: Target company name (optional).
            job_id:  UUID of related job application (optional).

        Returns:
            session_id, question, company.
        """
        user_msg = f"Company: {company}" if company else "General behavioral question."

        result = await self._gw().call(
            system=_BEHAVIORAL_SYSTEM.format(profile=_profile_str()),
            user=user_msg,
            max_tokens=256,
            temperature=0.8,
        )
        question = result.text.strip()

        jid = UUID(job_id) if job_id else None
        session_id = await self._repo.create_session(
            session_type="behavioral",
            question=question,
            job_id=jid,
            company=company,
        )

        logger.info("Behavioral question generated: session={}", session_id)
        return {
            "session_id": str(session_id),
            "session_type": "behavioral",
            "question": question,
            "company": company,
        }

    async def evaluate_answer(self, session_id: str, answer: str) -> dict:
        """LLM-evaluate an answer and persist feedback.

        Args:
            session_id: UUID of the session created by mock_system_design / mock_behavioral.
            answer:     The candidate's answer text.

        Returns:
            score, strengths, gaps, weak_areas, suggested_improvements, model_answer_hint.
        """
        session = await self._repo.get_session(UUID(session_id))
        if session is None:
            return {"error": f"Session {session_id} not found"}

        question = session["question"]

        result = await self._gw().call(
            system=_EVALUATE_SYSTEM.format(profile=_profile_str()),
            user=f"Question: {question}\n\nAnswer: {answer}",
            max_tokens=768,
        )

        evaluation = _parse_json(result.text)
        score = float(evaluation.get("score", 0.5))
        weak_areas = evaluation.get("weak_areas", [])

        await self._repo.save_answer(
            UUID(session_id),
            answer=answer,
            feedback=json.dumps(evaluation),
            score=score,
            weak_areas=weak_areas,
        )

        logger.info(
            "Answer evaluated: session={}, score={:.2f}, weak_areas={}",
            session_id, score, weak_areas,
        )
        return evaluation

    async def get_readiness(self, company: str | None = None) -> dict:
        """Return a readiness assessment, optionally for a specific company.

        Combines DB stats with an LLM narrative summary.

        Args:
            company: Company name to filter sessions (optional).

        Returns:
            overall_score, breakdown, top_weak_areas, readiness_level, summary, key_gaps.
        """
        stats = await self._repo.get_readiness(company=company)
        sessions = await self._repo.list_sessions(company=company, limit=20)

        if not sessions:
            return {
                **stats,
                "readiness_level": "not-ready",
                "summary": "No interview prep sessions found. Start with mock_system_design or mock_behavioral.",
                "key_gaps": [],
                "recommended_next": "Run a mock system design question to begin.",
            }

        session_summary = _format_sessions_for_prompt(sessions)

        result = await self._gw().call(
            system=_READINESS_SYSTEM.format(profile=_profile_str()),
            user=(
                f"Company: {company or 'General'}\n\n"
                f"Session history:\n{session_summary}\n\n"
                f"Overall avg score: {stats.get('overall_score')}\n"
                f"Top weak areas: {', '.join(stats.get('top_weak_areas', []))}"
            ),
            max_tokens=512,
        )

        narrative = _parse_json(result.text)
        return {**stats, **narrative}

    async def list_sessions(
        self,
        company: str | None = None,
        session_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List prep sessions, optionally filtered."""
        return await self._repo.list_sessions(
            company=company, session_type=session_type, limit=limit
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


def _format_sessions_for_prompt(sessions: list[dict]) -> str:
    lines = []
    for s in sessions:
        score_str = f"{s['score']:.2f}" if s.get("score") is not None else "not evaluated"
        lines.append(
            f"- [{s['session_type']}] Q: {s['question'][:100]}... | Score: {score_str}"
        )
    return "\n".join(lines)
