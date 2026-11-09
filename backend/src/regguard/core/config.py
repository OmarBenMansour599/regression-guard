"""Runtime settings, read from ``REGGUARD_*`` environment variables (and a local ``.env``).

Secrets are only ever supplied through the environment, never through YAML files.
"""

from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from regguard.core.errors import ConfigError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REGGUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM access (any OpenAI-compatible endpoint, e.g. Groq or OpenRouter)
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str | None = None
    judge_model: str | None = None

    # Execution policy (free tiers have strict rate limits: keep concurrency low)
    max_concurrency: int = Field(default=3, ge=1, le=64)
    request_timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=4, ge=0, le=10)

    # Integrations
    slack_webhook_url: SecretStr | None = None
    database_url: str = "sqlite+aiosqlite:///./.regguard/regguard.db"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"


def load_settings() -> Settings:
    """Load settings, converting validation failures into a readable ``ConfigError``."""
    try:
        return Settings()
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"Invalid configuration: {problems}") from exc
