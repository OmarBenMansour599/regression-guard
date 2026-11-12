"""Run results as JSON files: ``<runs_dir>/<run_id>/result.json``. Replaced by the DB in Phase 6."""

import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from regguard.core.errors import DataValidationError
from regguard.core.types import RunResult

RESULT_FILE = "result.json"


def new_run_id(now: datetime | None = None) -> str:
    """Sortable, unique id, e.g. ``20261112T153000Z-ab12cd``."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def save_run(runs_dir: Path, result: RunResult) -> Path:
    directory = runs_dir / result.meta.run_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RESULT_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read(path: Path) -> RunResult:
    try:
        return RunResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise DataValidationError(f"Cannot read run result {path}: {exc}") from exc


def load_run(runs_dir: Path, run_id: str) -> RunResult:
    """Load by full id or unique prefix (e.g. ``20261112T1530``)."""
    if not runs_dir.is_dir():
        raise DataValidationError(f"No runs found in {runs_dir}")
    matches = sorted(
        d for d in runs_dir.iterdir() if d.name.startswith(run_id) and (d / RESULT_FILE).is_file()
    )
    if not matches:
        raise DataValidationError(f"Run '{run_id}' not found in {runs_dir}")
    if len(matches) > 1 and matches[0].name != run_id:
        names = ", ".join(m.name for m in matches[:5])
        raise DataValidationError(f"Run id '{run_id}' is ambiguous: {names}")
    return _read(matches[0] / RESULT_FILE)


def list_runs(runs_dir: Path) -> list[RunResult]:
    """All stored runs, newest first. Unreadable files are skipped."""
    if not runs_dir.is_dir():
        return []
    results = []
    for directory in runs_dir.iterdir():
        path = directory / RESULT_FILE
        if path.is_file():
            try:
                results.append(_read(path))
            except DataValidationError:
                continue
    return sorted(results, key=lambda r: r.meta.started_at, reverse=True)
