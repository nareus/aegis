"""Job-analysis service: orchestrates the workflow and persists results."""

from uuid import UUID, uuid4

from loguru import logger

from aegis.agents.analyst import AnalystAgent
from aegis.agents.critic import CriticAgent
from aegis.agents.researcher import ResearcherAgent
from aegis.db.jobs_repository import JobApplicationRepository
from aegis.llm.gateway import LLMGateway
from aegis.profile import load_profile
from aegis.workflows.job_analysis.graph import build_job_analysis_graph
from aegis.workflows.job_analysis.state import JobAnalysisState


class JobAnalysisService:
    """End-to-end runner: graph + persistence."""

    def __init__(
        self,
        gateway: LLMGateway | None = None,
        repository: JobApplicationRepository | None = None,
    ) -> None:
        self._gateway = gateway
        self._repo = repository or JobApplicationRepository()

    async def analyze_and_save(self, url_or_text: str, source_url: str | None = None) -> dict:
        """Run the workflow on `url_or_text`, persist the job, return summary."""
        run_id = uuid4()
        gateway = self._gateway or LLMGateway()
        researcher = ResearcherAgent(gateway)
        analyst = AnalystAgent(gateway)
        critic = CriticAgent(gateway)

        graph = build_job_analysis_graph(researcher, analyst, critic).compile()

        initial: JobAnalysisState = {
            "run_id": run_id,
            "input": {"url_or_text": url_or_text},
            "profile": load_profile().as_prompt(),
            "researched": None,
            "analysis": None,
            "critic_feedback": None,
            "refinement_count": 0,
            "final_analysis": None,
            "error": None,
            "total_cost_usd": 0.0,
        }

        logger.info("Job analysis run starting", extra={"run_id": str(run_id)})
        final: JobAnalysisState = await graph.ainvoke(initial)

        if final.get("error") or final.get("final_analysis") is None:
            return {
                "run_id": str(run_id),
                "ok": False,
                "error": final.get("error", "no analysis produced"),
                "total_cost_usd": final.get("total_cost_usd", 0.0),
            }

        job_id = await self._persist(
            run_id=run_id,
            url=source_url,
            researched=final["researched"] or {},
            analysis=final["final_analysis"],
            critic_feedback=final.get("critic_feedback"),
            refinement_count=final.get("refinement_count", 0),
        )

        analysis = final["final_analysis"]
        return {
            "run_id": str(run_id),
            "job_id": str(job_id),
            "ok": True,
            "company": (final["researched"] or {}).get("company", "Unknown"),
            "role": (final["researched"] or {}).get("role", "Unknown"),
            "fit_score": analysis.get("fit_score"),
            "recommendation": analysis.get("recommendation"),
            "refinement_count": final.get("refinement_count", 0),
            "total_cost_usd": final.get("total_cost_usd", 0.0),
            "trace_url": f"/trace/{run_id}",
        }

    async def _persist(
        self,
        *,
        run_id: UUID,
        url: str | None,
        researched: dict,
        analysis: dict,
        critic_feedback: dict | None,
        refinement_count: int,
    ) -> UUID:
        return await self._repo.create_with_analysis(
            company=researched.get("company", "Unknown"),
            role=researched.get("role", "Unknown"),
            url=url,
            source_text=researched.get("raw_jd_text"),
            tech_stack=researched.get("tech_stack") or [],
            location=researched.get("location"),
            remote=researched.get("remote"),
            salary_range=researched.get("salary_range"),
            fit_score=analysis.get("fit_score"),
            fit_analysis=analysis,
            critic_feedback=critic_feedback,
            refinement_count=refinement_count,
            analysis_run_id=run_id,
        )
