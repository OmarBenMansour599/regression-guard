"""Baseline promotion and run comparison use cases (file storage; DB history comes in Phase 6)."""

import os
from datetime import UTC, datetime
from pathlib import Path

from regguard import __version__
from regguard.apps.config import AppConfig
from regguard.comparison.verdict import compare
from regguard.core.errors import ComparisonError
from regguard.core.types import BaselineFile, BaselineHeader, Comparison, RunResult, RunStatus
from regguard.storage.baseline_store import load_baseline, save_baseline
from regguard.storage.file_store import load_run


def promote_baseline(
    config: AppConfig,
    runs_dir: Path,
    run_id: str,
    *,
    name: str = "main",
    replace: bool = False,
    note: str = "",
    git_revision: str | None = None,
) -> tuple[BaselineFile, Path]:
    """Pin a stored run as the named baseline. Only COMPLETED runs of this app qualify."""
    run = load_run(runs_dir, run_id)
    if run.status is not RunStatus.COMPLETED:
        raise ComparisonError(
            f"Run {run.meta.run_id} has status {run.status.value}; only completed runs can "
            "become baselines"
        )
    if run.meta.app != config.name:
        raise ComparisonError(
            f"Run {run.meta.run_id} belongs to app '{run.meta.app}', not '{config.name}'"
        )
    baseline = BaselineFile(
        header=BaselineHeader(
            name=name,
            app=config.name,
            source_run_id=run.meta.run_id,
            promoted_at=datetime.now(UTC),
            git_sha=git_revision,
            note=note,
            regguard_version=__version__,
        ),
        run=run,
    )
    path = save_baseline(config.baselines_dir, baseline, replace=replace)
    return baseline, path


def comparison_path(runs_dir: Path, comparison: Comparison) -> Path:
    label = comparison.baseline_name or comparison.baseline_run_id
    return runs_dir / comparison.candidate_run_id / f"comparison-{label}.json"


def save_comparison(runs_dir: Path, comparison: Comparison) -> Path:
    path = comparison_path(runs_dir, comparison)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(comparison.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def ensure_baseline_exists(config: AppConfig, name: str) -> None:
    """Fail fast (before any API call) when ``run --baseline`` names a missing baseline."""
    load_baseline(config.baselines_dir, name)


def compare_with_baseline(
    config: AppConfig,
    runs_dir: Path,
    candidate: RunResult,
    *,
    baseline_name: str | None = "main",
    against_run: str | None = None,
    allow_dataset_change: bool = False,
) -> tuple[Comparison, Path]:
    """Compare ``candidate`` with a named baseline, or directly with another stored run."""
    if against_run is not None:
        reference, name = load_run(runs_dir, against_run), None
    else:
        if baseline_name is None:
            raise ComparisonError("Give a baseline name or a run id to compare against")
        reference, name = load_baseline(config.baselines_dir, baseline_name).run, baseline_name
    comparison = compare(
        reference,
        candidate,
        config.gate,
        baseline_name=name,
        allow_dataset_change=allow_dataset_change,
    )
    return comparison, save_comparison(runs_dir, comparison)
