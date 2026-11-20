"""Report use case: gather run, comparison, dataset inputs and history, write HTML + Markdown."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from regguard.apps.config import AppConfig
from regguard.apps.registry import get_app
from regguard.core.config import Settings
from regguard.core.errors import ConfigError, DataValidationError
from regguard.core.types import Comparison, RunResult
from regguard.reporting.html import ReportData, render_html
from regguard.reporting.markdown import render_markdown
from regguard.services.datasets import load_app_dataset
from regguard.services.history_service import HISTORY_ERRORS, history

TREND_METRICS = (
    "pass_rate",
    "schema_valid",
    "label_exact",
    "summary_format",
    "summary_judge",
    "summary_similarity",
    "macro_f1",
)
TREND_RUNS = 20


@dataclass(frozen=True)
class ReportFiles:
    html: Path
    markdown: Path
    notes: list[str] = field(default_factory=list)


def _dataset_context(
    config: AppConfig, run: RunResult
) -> tuple[dict[str, Mapping[str, str]], dict[str, Mapping[str, Any]], list[str]]:
    """Inputs and golden labels of the run's cases, only if the dataset is unchanged."""
    version = run.meta.dataset_version
    try:
        dataset = load_app_dataset(config, get_app(config.app), version)
    except (ConfigError, DataValidationError):
        return {}, {}, [f"Dataset {version} could not be loaded: inputs are not shown."]
    if dataset.content_hash != run.meta.dataset_hash:
        return {}, {}, [f"Dataset {version} changed since this run: inputs are not shown."]
    ids = {c.case_id for c in run.cases}
    cases = [c for c in dataset.cases if c.id in ids]
    return {c.id: c.input for c in cases}, {c.id: c.expected for c in cases}, []


def _trends(settings: Settings, run: RunResult) -> tuple[dict[str, list[float]], list[str]]:
    """Recent values of key metrics for runs of the same app and prompt version."""
    if not settings.record_history:
        return {}, []
    trends: dict[str, list[float]] = {}
    try:
        with history(settings) as repo:
            for metric in TREND_METRICS:
                series = repo.metric_series(metric, app=run.meta.app, limit=TREND_RUNS * 3)
                values = [v for r, v in series if r.prompt_version == run.meta.prompt_version][
                    -TREND_RUNS:
                ]
                if len(values) >= 2:
                    trends[metric] = values
    except HISTORY_ERRORS as exc:
        return {}, [f"History unavailable, no trends ({type(exc).__name__})."]
    return trends, []


def write_report(
    config: AppConfig,
    settings: Settings,
    run: RunResult,
    *,
    comparison: Comparison | None = None,
    baseline: RunResult | None = None,
) -> ReportFiles:
    inputs, expected, notes = _dataset_context(config, run)
    trends, trend_notes = _trends(settings, run)
    data = ReportData(
        run=run,
        comparison=comparison,
        baseline=baseline,
        inputs=inputs,
        expected=expected,
        trends=trends,
        notes=[*notes, *trend_notes],
    )
    directory = settings.reports_dir
    directory.mkdir(parents=True, exist_ok=True)
    html_path = directory / f"{run.meta.run_id}.html"
    md_path = directory / f"{run.meta.run_id}.md"
    html_path.write_text(render_html(data), encoding="utf-8")
    md_path.write_text(
        render_markdown(run, comparison, baseline=baseline), encoding="utf-8", newline="\n"
    )
    return ReportFiles(html=html_path, markdown=md_path, notes=list(data.notes))
