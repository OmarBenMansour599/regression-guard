"""Load and validate prompt files. One file per version: ``<dir>/<version>.yaml``."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from regguard.core.errors import DataValidationError
from regguard.prompts.models import PromptConfig


def load_prompt(path: Path) -> PromptConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DataValidationError(f"Cannot read prompt file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DataValidationError(f"Prompt file {path} must contain a YAML mapping")
    try:
        prompt = PromptConfig.model_validate(raw)
    except ValidationError as exc:
        raise DataValidationError(f"Invalid prompt file {path}:\n{exc}") from exc
    if prompt.version != path.stem:
        raise DataValidationError(
            f"Prompt file {path.name} declares version '{prompt.version}'; "
            f"file name and version must match"
        )
    return prompt


def discover_prompts(directory: Path) -> dict[str, PromptConfig]:
    """Load every ``*.yaml`` prompt in ``directory``, keyed by version."""
    if not directory.is_dir():
        raise DataValidationError(f"Prompt directory not found: {directory}")
    return {p.stem: load_prompt(p) for p in sorted(directory.glob("*.yaml"))}


def load_prompt_version(directory: Path, version: str) -> PromptConfig:
    path = directory / f"{version}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in directory.glob("*.yaml"))) or "none"
        raise DataValidationError(
            f"Prompt version '{version}' not found in {directory} (available: {available})"
        )
    return load_prompt(path)
