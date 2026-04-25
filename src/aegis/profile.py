"""Profile loader -- reads the candidate profile from a YAML file.

The profile is treated as opaque structured data by agents and prompts.
Path is configured via `AEGIS_PROFILE_PATH` (default `./profile.yaml`).
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


class Profile(BaseModel):
    skills: list[str] = []
    target_roles: list[str] = []
    experience_years: int = 0
    preferred_locations: list[str] = []
    deal_breakers: list[str] = []
    summary: str = ""

    def as_prompt(self) -> str:
        """Render the profile as a flat string for inclusion in LLM prompts."""
        lines: list[str] = []
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        lines.extend([
            f"Skills: {', '.join(self.skills)}",
            f"Target roles: {', '.join(self.target_roles)}",
            f"Experience: {self.experience_years} years",
            f"Preferred locations: {', '.join(self.preferred_locations)}",
            f"Deal breakers: {', '.join(self.deal_breakers)}",
        ])
        return "\n".join(lines)


@lru_cache
def load_profile() -> Profile:
    """Load the profile from disk, cached for the process lifetime."""
    from aegis.config import settings

    path = Path(settings.aegis_profile_path)
    if not path.exists():
        return Profile()
    data = yaml.safe_load(path.read_text()) or {}
    return Profile(**data)
