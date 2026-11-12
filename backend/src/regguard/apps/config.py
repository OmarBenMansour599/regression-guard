"""``regguard.yaml``: binds an application spec to its prompt and dataset directories.

Relative paths are resolved against the directory containing the YAML file.
Metrics and thresholds are added to this file in Phase 5.
"""

from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from regguard.core.errors import ConfigError
from regguard.core.types import FrozenModel


class JudgeConfig(FrozenModel):
    model: str
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class AppConfig(FrozenModel):
    name: str
    app: str  # registered AppSpec name
    prompts_dir: Path
    datasets_dir: Path | None = None
    judge: JudgeConfig | None = None


def load_app_config(path: Path) -> AppConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read app config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"App config {path} must contain a YAML mapping")
    try:
        config = AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid app config {path}:\n{exc}") from exc
    base = path.parent.resolve()
    return config.model_copy(
        update={
            "prompts_dir": (base / config.prompts_dir).resolve(),
            "datasets_dir": (base / config.datasets_dir).resolve() if config.datasets_dir else None,
        }
    )
