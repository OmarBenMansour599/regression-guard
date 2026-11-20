"""``regguard.yaml``: binds an application spec to its prompt and dataset directories.

Relative paths are resolved against the directory containing the YAML file.
The optional ``gate:`` block sets comparison thresholds (see ``core/gating.py``).
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from regguard.core.errors import ConfigError
from regguard.core.gating import GateConfig
from regguard.core.types import FrozenModel


class JudgeConfig(FrozenModel):
    """LLM judge for the summary. Its model and parameters live in the versioned judge prompt."""

    prompts_dir: Path
    version: str = "v1"
    enabled: bool = True


NotifyEvent = Literal["fail", "warn", "error", "drift"]


class NotifyConfig(FrozenModel):
    """Which events send a Slack message when a command runs with ``--notify``.

    fail/warn: comparison verdicts; error: a run with status ERROR; drift: a new drift
    episode (one message per episode, not one per run).
    """

    # Not called "on": YAML 1.1 (PyYAML) reads a bare `on` key as the boolean True.
    events: tuple[NotifyEvent, ...] = ("fail", "error", "drift")


class AppConfig(FrozenModel):
    name: str
    app: str  # registered AppSpec name
    prompts_dir: Path
    datasets_dir: Path | None = None
    baselines_dir: Path = Path("baselines")
    judge: JudgeConfig | None = None
    gate: GateConfig = Field(default_factory=GateConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)


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
    judge = config.judge
    if judge is not None:
        judge = judge.model_copy(update={"prompts_dir": (base / judge.prompts_dir).resolve()})
    return config.model_copy(
        update={
            "judge": judge,
            "prompts_dir": (base / config.prompts_dir).resolve(),
            "datasets_dir": (base / config.datasets_dir).resolve() if config.datasets_dir else None,
            "baselines_dir": (base / config.baselines_dir).resolve(),
        }
    )
