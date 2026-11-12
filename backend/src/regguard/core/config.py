"""Runtime settings, read from ``REGGUARD_*`` environment variables (and a local ``.env``).

Secrets are only ever supplied through the environment, never through YAML files.
Model choice and parameters are NOT settings: they live in versioned prompt files,
because changing them is exactly what we want to detect and review.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from regguard.core.errors import ConfigError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REGGUARD_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM access (any OpenAI-compatible endpoint, e.g. OpenRouter or Groq)
    llm_provider: Literal["openai_compatible", "mock"] = "openai_compatible"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str | None = None  # local override of the prompt's model, for experiments only

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


def find_dotenv(start: Path | None = None) -> Path | None:
    """Return the nearest ``.env`` between ``start`` (default: cwd) and the git repo root.

    Outside a git repository only ``start`` itself is checked, so we never pick up
    unrelated ``.env`` files from parent directories.
    """
    start = (start or Path.cwd()).resolve()
    candidates = [start, *start.parents]
    repo_root = next((d for d in candidates if (d / ".git").exists()), None)
    search = candidates[: candidates.index(repo_root) + 1] if repo_root else [start]
    return next((d / ".env" for d in search if (d / ".env").is_file()), None)


def load_settings() -> Settings:
    """Load settings, converting validation failures into a readable ``ConfigError``."""
    try:
        return Settings(_env_file=find_dotenv())
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"Invalid configuration: {problems}") from exc
