"""TypedDict state for the job_analysis workflow."""

from typing import TypedDict
from uuid import UUID


class JobAnalysisState(TypedDict, total=False):
    run_id: UUID
    input: dict                       # original {"url_or_text": "..."}
    profile: str                      # rendered profile prompt
    researched: dict | None           # ResearcherAgent output
    analysis: dict | None             # AnalystAgent output (latest)
    critic_feedback: dict | None      # CriticAgent output (latest)
    refinement_count: int
    final_analysis: dict | None
    error: str | None
    total_cost_usd: float
