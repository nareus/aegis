"""Internal source: reads job tracker data from DB for the daily briefing."""

from loguru import logger

from aegis.db.jobs_repository import JobApplicationRepository
from aegis.sources.base import SourceResult


class JobsSource:
    """Reads job application data from the internal DB."""

    name = "jobs"

    def __init__(self) -> None:
        self._repo = JobApplicationRepository()

    async def fetch(self) -> SourceResult:
        try:
            follow_ups = await self._repo.get_follow_ups(stale_days=7)
            top_fits = await self._repo.get_by_fit_score(min_score=0.7)
            all_jobs = await self._repo.list_all(limit=100)

            status_counts: dict[str, int] = {}
            for job in all_jobs:
                s = job.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1

            data = {
                "follow_ups": _summarize_jobs(follow_ups),
                "top_fits_not_applied": _summarize_jobs(top_fits),
                "status_counts": status_counts,
                "total": len(all_jobs),
            }

            logger.info(
                "Jobs source: {} total, {} need follow-up, {} top fits",
                len(all_jobs),
                len(follow_ups),
                len(top_fits),
            )
            return SourceResult(source=self.name, ok=True, data=data)

        except Exception as e:
            logger.warning("Jobs source failed: {}", str(e))
            return SourceResult(source=self.name, ok=False, error=str(e))


def _summarize_jobs(jobs: list[dict]) -> list[dict]:
    """Slim down job records for the briefing context."""
    return [
        {
            "id": str(j["id"]),
            "company": j["company"],
            "role": j["role"],
            "status": j["status"],
            "fit_score": j.get("fit_score"),
            "last_activity": str(j.get("last_activity", "")),
        }
        for j in jobs
    ]
