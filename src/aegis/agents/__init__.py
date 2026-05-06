"""Agent abstractions: shared base class with auto-tracing, and concrete agents."""

from aegis.agents.analyst import AnalystAgent
from aegis.agents.base import AgentBase, AgentResult
from aegis.agents.critic import CriticAgent
from aegis.agents.researcher import ResearcherAgent

__all__ = [
    "AgentBase",
    "AgentResult",
    "ResearcherAgent",
    "AnalystAgent",
    "CriticAgent",
]
