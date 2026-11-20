"""Run history use cases: record runs and comparisons, import old run files, list, trend.

History is secondary to the result files (ADR 0002/0005): a database problem while
recording is reported as a warning and never fails a run.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from regguard.core.config import Settings
from regguard.core.errors import RegGuardError
from regguard.core.types import Comparison, RunResult
from regguard.storage.db.repository import HistoryRepository, RunRecord
from regguard.storage.db.session import (
    current_revision,
    head_revision,
    make_engine,
    open_history,
    upgrade,
)
from regguard.storage.file_store import RESULT_FILE

# ImportError: e.g. a PostgreSQL URL without the `postgres` extra (driver) installed.
HISTORY_ERRORS = (SQLAlchemyError, OSError, ImportError, RegGuardError)
_RECORD_ERRORS = HISTORY_ERRORS


@contextmanager
def history(settings: Settings) -> Iterator[HistoryRepository]:
    """A repository on the up-to-date history database; the engine is closed afterwards."""
    engine = open_history(settings.database_url)
    try:
        yield HistoryRepository(engine)
    finally:
        engine.dispose()


def _warning(what: str, exc: Exception) -> str:
    return (
        f"{what} not recorded in history ({type(exc).__name__}: {exc}). The result file is saved."
    )


def record_run(settings: Settings, result: RunResult) -> str | None:
    """Store a run in the history database. Returns a warning message instead of raising."""
    if not settings.record_history:
        return None
    try:
        with history(settings) as repo:
            repo.save_run(result)
    except _RECORD_ERRORS as exc:
        return _warning("Run", exc)
    return None


def record_comparison(
    settings: Settings, comparison: Comparison, candidate: RunResult
) -> str | None:
    """Store a comparison (and its candidate run if missing). Returns a warning, never raises."""
    if not settings.record_history:
        return None
    try:
        with history(settings) as repo:
            repo.save_run(candidate)  # no-op when already stored
            repo.save_comparison(comparison)
    except _RECORD_ERRORS as exc:
        return _warning("Comparison", exc)
    return None


@dataclass
class ImportSummary:
    imported: int = 0
    skipped: int = 0  # already in the database
    comparisons: int = 0
    failed: list[str] = field(default_factory=list)


def import_runs(settings: Settings) -> ImportSummary:
    """Backfill the history database from ``<runs_dir>/*/result.json``. Safe to repeat."""
    summary = ImportSummary()
    runs_dir = settings.runs_dir
    if not runs_dir.is_dir():
        return summary
    with history(settings) as repo:
        for directory in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
            path = directory / RESULT_FILE
            if not path.is_file():
                continue
            try:
                result = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError) as exc:
                summary.failed.append(f"{path}: {type(exc).__name__}")
                continue
            if repo.save_run(result):
                summary.imported += 1
            else:
                summary.skipped += 1
            for comparison_file in sorted(directory.glob("comparison-*.json")):
                try:
                    comparison = Comparison.model_validate_json(
                        comparison_file.read_text(encoding="utf-8")
                    )
                except (OSError, ValidationError) as exc:
                    summary.failed.append(f"{comparison_file}: {type(exc).__name__}")
                    continue
                repo.save_comparison(comparison)
                summary.comparisons += 1
    return summary


def upgrade_database(settings: Settings) -> tuple[str | None, str]:
    """Apply migrations to any configured database. Returns (revision before, after)."""
    engine = make_engine(settings.database_url)
    try:
        before = current_revision(engine)
        upgrade(engine)
        return before, head_revision()
    finally:
        engine.dispose()


def list_history(settings: Settings, *, app: str | None, limit: int) -> list[RunRecord]:
    with history(settings) as repo:
        return repo.list_runs(app=app, limit=limit)


def metric_trend(
    settings: Settings, metric: str, *, app: str | None, limit: int
) -> list[tuple[RunRecord, float]]:
    with history(settings) as repo:
        return repo.metric_series(metric, app=app, limit=limit)
