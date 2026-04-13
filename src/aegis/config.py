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

    # Data sources
    github_token: str = ""
    github_username: str = "narenarya3"
    leetcode_session: str = ""

    # Infrastructure
    database_url: str = "postgresql://aegis:aegis@localhost:5432/aegis"
    redis_url: str = "redis://localhost:6379/0"

    # Scheduler
    aegis_briefing_cron: str = "0 7 * * *"
    aegis_timezone: str = "Asia/Singapore"

    @property
    def is_production(self) -> bool:
        return self.aegis_env == "prod"


settings = Settings()
