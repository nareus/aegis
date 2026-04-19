"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Core
    aegis_env: str = "local"
    log_level: str = "INFO"

    # LLM
    anthropic_api_key: str = ""
    aegis_llm_model: str = "claude-sonnet-4-5"
    aegis_llm_max_cost_usd_per_run: float = 0.50

    # Profile (used for job fit scoring and interview prep)
    aegis_profile_skills: str = "python,golang,distributed-systems,postgresql,redis,docker,kubernetes,fastapi,async-programming,system-design"
    aegis_profile_target_roles: str = "backend-engineer,platform-engineer,ai-engineer"
    aegis_profile_experience_years: int = 3
    aegis_profile_preferred_locations: str = "singapore,remote"
    aegis_profile_deal_breakers: str = "php,wordpress"

    # Data sources
    github_token: str = ""
    github_username: str = ""
    leetcode_username: str = ""
    leetcode_session: str = ""

    # Infrastructure
    database_url: str = "postgresql://aegis:aegis@localhost:5432/aegis"
    redis_url: str = "redis://localhost:6379/0"

    # Scheduler
    aegis_briefing_cron: str = "0 7 * * *"
    aegis_timezone: str = "Asia/Singapore"

    # ── Derived properties ───────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.aegis_env == "prod"

    @property
    def skills_list(self) -> list[str]:
        return [s.strip() for s in self.aegis_profile_skills.split(",") if s.strip()]

    @property
    def target_roles_list(self) -> list[str]:
        return [r.strip() for r in self.aegis_profile_target_roles.split(",") if r.strip()]

    @property
    def preferred_locations_list(self) -> list[str]:
        return [loc.strip() for loc in self.aegis_profile_preferred_locations.split(",") if loc.strip()]

    @property
    def deal_breakers_list(self) -> list[str]:
        return [d.strip() for d in self.aegis_profile_deal_breakers.split(",") if d.strip()]

    # ── Validation helpers ───────────────────────────────────────────────────

    def check(self) -> list[str]:
        """Return a list of warning strings for missing/placeholder config values.

        Call at startup to surface problems early instead of failing mid-request.
        Empty list means everything required is set.
        """
        warnings: list[str] = []

        _PLACEHOLDER_PREFIXES = ("sk-ant-", "ghp_", "your-")

        def _missing(value: str, label: str, required: bool = True) -> None:
            if not value or any(value.startswith(p) for p in _PLACEHOLDER_PREFIXES):
                prefix = "REQUIRED" if required else "optional"
                warnings.append(f"  [{prefix}] {label} is not set")

        _missing(self.anthropic_api_key, "ANTHROPIC_API_KEY")
        _missing(self.github_token, "GITHUB_TOKEN", required=False)
        _missing(self.github_username, "GITHUB_USERNAME", required=False)
        _missing(self.leetcode_username, "LEETCODE_USERNAME", required=False)
        _missing(self.leetcode_session, "LEETCODE_SESSION", required=False)

        return warnings


settings = Settings()
