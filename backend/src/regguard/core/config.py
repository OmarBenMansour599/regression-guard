"""Runtime settings, read from ``REGGUARD_*`` environment variables (and a local ``.env``).

Secrets are only ever supplied through the environment, never through YAML files.
Model choice and parameters are NOT settings: they live in versioned prompt files,
because changing them is exactly what we want to detect and review.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
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
    requests_per_minute: int = Field(default=15, ge=1, le=10_000)  # OpenRouter free tier: 20
    max_error_rate: float = Field(default=0.10, ge=0.0, le=1.0)  # above this, run = ERROR

    # Local storage (relative to the working directory; both are git-ignored)
    cache_dir: Path = Path(".regguard/cache")
    runs_dir: Path = Path("runs")
    reports_dir: Path = Path("reports")

    # Integrations
    slack_webhook_url: SecretStr | None = None
    # Run history (Phase 6). Local SQLite by default (git-ignored, created on first use);
    # PostgreSQL e.g. postgresql+psycopg://user:pass@host/db (install the `postgres` extra).
    database_url: str = "sqlite:///.regguard/regguard.db"
    record_history: bool = True  # record every run and comparison in the history database

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    @field_validator("llm_api_key", "slack_webhook_url", mode="before")
    @classmethod
    def _clean_secret(cls, value: object) -> object:
        """Pasted secrets often end with a line break or space (e.g. GitHub secrets).

        Leading/trailing whitespace is removed; whitespace inside is an error. The message
        never includes the value.
        """
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            return None
        if any(ch.isspace() for ch in cleaned):
            raise ValueError("contains spaces or line breaks; paste the secret again")
        return cleaned


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
