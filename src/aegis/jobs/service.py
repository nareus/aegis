"""Job service -- coordinates repository and analyzer."""

from uuid import UUID

from loguru import logger

from aegis.db.jobs_repository import JobApplicationRepository
from aegis.jobs.analyzer import JobAnalyzer, JobAnalysisResult
from aegis.llm.gateway import LLMGateway


class JobService:
    """High-level service for job tracking operations."""

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._repo = JobApplicationRepository()
        self._gateway = gateway
        self._analyzer: JobAnalyzer | None = None

    def _get_analyzer(self) -> JobAnalyzer:
        if self._analyzer is None:
            if self._gateway is None:
                self._gateway = LLMGateway()
            self._analyzer = JobAnalyzer(self._gateway)
        return self._analyzer

    async def add_job(self, text: str, url: str | None = None) -> dict:
        """Parse a job description, score fit, and save to tracker.

        Args:
            text: Raw JD text (or content extracted from URL).
            url: Optional source URL (e.g. LinkedIn posting).

        Returns:
            Dict with job_id, company, role, fit_score, and fit_analysis.
        """
        analyzer = self._get_analyzer()
        analysis = await analyzer.analyze(text)

        job_id = await self._repo.create(
            company=analysis.company,
            role=analysis.role,
            url=url,
            source_text=text,
            fit_score=analysis.fit_score,
            fit_analysis=analysis.fit_analysis,
            tech_stack=analysis.tech_stack,
            salary_range=analysis.salary_range,
            location=analysis.location,
            remote=analysis.remote,
        )

        logger.info("Job saved: {} at {} (fit: {:.1f})", analysis.role, analysis.company, analysis.fit_score)

        return {
            "job_id": str(job_id),
            "company": analysis.company,
            "role": analysis.role,
            "fit_score": analysis.fit_score,
            "fit_analysis": analysis.fit_analysis,
        }

    async def list_jobs(self, status: str | None = None) -> list[dict]:
        """List all tracked jobs, optionally filtered by status."""
        return await self._repo.list_all(status=status)

    async def get_job(self, job_id: str) -> dict | None:
        """Get full details of a job application."""
        return await self._repo.get(UUID(job_id))

    async def update_status(self, job_id: str, status: str, notes: str | None = None) -> bool:
        """Update the status of a job application."""
        return await self._repo.update_status(UUID(job_id), status, notes)

    async def get_follow_ups(self, stale_days: int = 7) -> list[dict]:
        """Get applications that need follow-up."""
        return await self._repo.get_follow_ups(stale_days)

    async def get_top_fits(self, min_score: float = 0.7) -> list[dict]:
        """Get highest-fit saved jobs not yet applied to."""
        return await self._repo.get_by_fit_score(min_score)
