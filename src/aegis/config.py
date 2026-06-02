"""Application configuration via environment variables."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


def _aegis_home() -> Path:
    """Resolve AEGIS_HOME — where tool-mode keeps .env, profile, compose, data."""
    env = os.environ.get("AEGIS_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "aegis"


AEGIS_HOME = _aegis_home()


class Settings(BaseSettings):
    model_config = {
        "env_file": str(AEGIS_HOME / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # Core
    aegis_env: str = "local"
    log_level: str = "INFO"

    # LLM
    anthropic_api_key: str = ""
    aegis_llm_model: str = "claude-sonnet-4-5"
    aegis_llm_max_cost_usd_per_run: float = 0.50
    aegis_llm_max_cost_usd_per_day: float = 5.0    # 0 disables the daily cap

    # Workflows
    aegis_max_refinements: int = 2

    # Profile (path to YAML; see profile.example.yaml)
    aegis_profile_path: str = str(AEGIS_HOME / "profile.yaml")

    # Data sources
    github_token: str = ""
    github_username: str = "nareus"

    # Infrastructure
    database_url: str = "postgresql://aegis:aegis@localhost:5432/aegis"
    redis_url: str = "redis://localhost:6379/0"

    # ── Derived properties ───────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.aegis_env == "prod"

    # ── Validation helpers ───────────────────────────────────────────────────

    def check(self) -> list[str]:
        """Return a list of warning strings for missing/placeholder config values."""
        warnings: list[str] = []

        def _missing(value: str, label: str, required: bool = True) -> None:
            is_placeholder = not value or value.endswith("...")
            if is_placeholder:
                prefix = "REQUIRED" if required else "optional"
                warnings.append(f"  [{prefix}] {label} is not set")

        _missing(self.anthropic_api_key, "ANTHROPIC_API_KEY")
        _missing(self.github_token, "GITHUB_TOKEN", required=False)
        _missing(self.github_username, "GITHUB_USERNAME", required=False)

        if not Path(self.aegis_profile_path).exists():
            warnings.append(
                f"  [optional] profile file not found at {self.aegis_profile_path} "
                f"-- copy profile.example.yaml to {self.aegis_profile_path}"
            )

        return warnings


settings = Settings()
