"""Pinned baselines as committed JSON files: ``<baselines_dir>/<name>.json`` (ADR 0002).

Baselines change only through ``regguard baseline promote``; overwriting needs ``replace=True``.
"""

import os
import re
from pathlib import Path

from pydantic import ValidationError

from regguard.core.errors import DataValidationError
from regguard.core.types import BaselineFile

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def baseline_path(baselines_dir: Path, name: str) -> Path:
    if not NAME_PATTERN.match(name):
        raise DataValidationError(
            f"Invalid baseline name '{name}': use lowercase letters, digits, '-' or '_' (max 64)"
        )
    return baselines_dir / f"{name}.json"


def save_baseline(baselines_dir: Path, baseline: BaselineFile, *, replace: bool = False) -> Path:
    path = baseline_path(baselines_dir, baseline.header.name)
    if path.exists() and not replace:
        raise DataValidationError(
            f"Baseline '{baseline.header.name}' already exists ({path}); "
            "pass --replace to overwrite it"
        )
    baselines_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(baseline.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path


def _read(path: Path) -> BaselineFile:
    try:
        return BaselineFile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise DataValidationError(f"Cannot read baseline {path}: {exc}") from exc


def load_baseline(baselines_dir: Path, name: str) -> BaselineFile:
    path = baseline_path(baselines_dir, name)
    if not path.is_file():
        raise DataValidationError(
            f"Baseline '{name}' not found in {baselines_dir}. "
            "Create it with: regguard baseline promote <run_id>"
        )
    return _read(path)


def list_baselines(baselines_dir: Path) -> list[BaselineFile]:
    """All readable baselines, sorted by name."""
    if not baselines_dir.is_dir():
        return []
    return [_read(p) for p in sorted(baselines_dir.glob("*.json"))]
