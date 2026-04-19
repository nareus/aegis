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
    github_username: str = "narenarya3"
    leetcode_username: str = ""       # your LeetCode username (e.g. narenarya3)
    leetcode_session: str = ""        # LEETCODE_SESSION cookie for submission history

    # Infrastructure
    database_url: str = "postgresql://aegis:aegis@localhost:5432/aegis"
    redis_url: str = "redis://localhost:6379/0"

    # Scheduler
    aegis_briefing_cron: str = "0 7 * * *"
    aegis_timezone: str = "Asia/Singapore"

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
        return [l.strip() for l in self.aegis_profile_preferred_locations.split(",") if l.strip()]

    @property
    def deal_breakers_list(self) -> list[str]:
        return [d.strip() for d in self.aegis_profile_deal_breakers.split(",") if d.strip()]


settings = Settings()
