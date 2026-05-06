"""Job service: thin facade over the analysis workflow and job repository."""

from uuid import UUID

from aegis.db.jobs_repository import JobApplicationRepository
from aegis.llm.gateway import LLMGateway
from aegis.workflows.job_analysis.service import JobAnalysisService


class JobService:
    """High-level operations the API and MCP server expose."""

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._repo = JobApplicationRepository()
        self._analysis = JobAnalysisService(gateway=gateway, repository=self._repo)

    async def add_job(self, text: str, url: str | None = None) -> dict:
        """Run the multi-agent workflow on a JD and persist the result."""
        return await self._analysis.analyze_and_save(text, source_url=url)

    async def list_jobs(self, status: str | None = None) -> list[dict]:
        return await self._repo.list_all(status=status)

    async def get_job(self, job_id: str) -> dict | None:
        return await self._repo.get(UUID(job_id))

    async def update_status(self, job_id: str, status: str, notes: str | None = None) -> bool:
        return await self._repo.update_status(UUID(job_id), status, notes)

    async def get_follow_ups(self, stale_days: int = 7) -> list[dict]:
        return await self._repo.get_follow_ups(stale_days)

    async def get_top_fits(self, min_score: float = 0.7) -> list[dict]:
        return await self._repo.get_by_fit_score(min_score)
