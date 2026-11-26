"""Read-only queries behind the dashboard API (Phase 8, ADR 0007).

Nothing here writes: no run, no baseline promotion, no stored comparison. Comparisons asked
for by the dashboard are computed on the fly and discarded. Email text is only returned for
runs whose dataset is unchanged (same rule as the HTML report).
"""

from datetime import datetime
from typing import Any

from pydantic import Field

from regguard import __version__
from regguard.apps.config import AppConfig
from regguard.apps.registry import get_app
from regguard.comparison.drift import drift_report
from regguard.comparison.verdict import compare
from regguard.core.config import Settings
from regguard.core.errors import ConfigError, DataValidationError, NotFoundError
from regguard.core.types import Comparison, DriftReport, FrozenModel, RunResult, Verdict
from regguard.datasets.lint import dataset_stats
from regguard.prompts.loader import discover_prompts
from regguard.services.datasets import load_app_dataset
from regguard.services.history_service import HISTORY_ERRORS, history
from regguard.services.report_service import dataset_context
from regguard.storage.baseline_store import list_baselines, load_baseline

# Shown in the runs table; the full set is in the run detail.
HEADLINE_METRICS = ("pass_rate", "schema_valid", "label_exact", "summary_judge")
MAX_PAGE = 200
MAX_TREND_POINTS = 500


class HealthInfo(FrozenModel):
    status: str  # "ok" or "degraded" (history database unavailable)
    version: str
    app: str
    database: str  # "ok" or the error type
    runs: int


class PromptInfo(FrozenModel):
    version: str
    description: str
    model: str
    content_hash: str
    created_at: str | None = None


class DatasetInfo(FrozenModel):
    version: str
    content_hash: str
    cases: int
    critical: int
    labels: dict[str, int] = Field(default_factory=dict)
    difficulty: dict[str, int] = Field(default_factory=dict)


class BaselineSummary(FrozenModel):
    name: str
    source_run_id: str
    promoted_at: datetime
    note: str
    git_sha: str | None
    prompt_version: str
    prompt_hash: str
    model: str
    dataset_version: str
    cases: int
    metrics: dict[str, float] = Field(default_factory=dict)


class AppOverview(FrozenModel):
    name: str
    app: str
    prompts: list[PromptInfo]
    dataset: DatasetInfo | None
    baselines: list[BaselineSummary]
    recorded_prompt_versions: list[str]
    notes: list[str] = Field(default_factory=list)


class RunSummary(FrozenModel):
    run_id: str
    prompt_version: str
    dataset_version: str
    model: str
    status: str
    trigger: str
    started_at: datetime
    cases: int
    api_calls: int
    cache_hits: int
    metrics: dict[str, float] = Field(default_factory=dict)
    verdict: Verdict | None = None  # latest stored comparison, if any
    verdict_baseline: str | None = None


class RunPage(FrozenModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class RunDetail(FrozenModel):
    run: RunResult
    comparisons: list[Comparison]
    inputs: dict[str, dict[str, str]] = Field(default_factory=dict)
    expected: dict[str, dict[str, Any]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class TrendPoint(FrozenModel):
    run_id: str
    started_at: datetime
    prompt_version: str
    value: float
    fresh: bool  # real API calls only (cached answers cannot show drift)


def health(config: AppConfig, settings: Settings) -> HealthInfo:
    try:
        with history(settings) as repo:
            runs = repo.count_runs()
    except HISTORY_ERRORS as exc:
        return HealthInfo(
            status="degraded",
            version=__version__,
            app=config.name,
            database=type(exc).__name__,
            runs=0,
        )
    return HealthInfo(status="ok", version=__version__, app=config.name, database="ok", runs=runs)


def _prompts(config: AppConfig) -> list[PromptInfo]:
    return [
        PromptInfo(
            version=p.version,
            description=p.description,
            model=p.model.model,
            content_hash=p.content_hash,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in discover_prompts(config.prompts_dir).values()
    ]


def _dataset(config: AppConfig) -> DatasetInfo:
    spec = get_app(config.app)
    dataset = load_app_dataset(config, spec)
    stats = dataset_stats(dataset, label_field=spec.label_field)
    return DatasetInfo(
        version=dataset.manifest.version,
        content_hash=dataset.content_hash,
        cases=stats["flags"]["total"],
        critical=stats["flags"]["critical"],
        labels=stats.get("labels", {}),
        difficulty=stats["difficulty"],
    )


def _baseline_summary(name: str, config: AppConfig) -> BaselineSummary:
    file = load_baseline(config.baselines_dir, name)
    run = file.run
    return BaselineSummary(
        name=file.header.name,
        source_run_id=file.header.source_run_id,
        promoted_at=file.header.promoted_at,
        note=file.header.note,
        git_sha=file.header.git_sha,
        prompt_version=run.meta.prompt_version,
        prompt_hash=run.meta.prompt_hash,
        model=run.meta.model,
        dataset_version=run.meta.dataset_version,
        cases=len({c.case_id for c in run.cases}),
        metrics={k: v.value for k, v in run.aggregates.items()},
    )


def overview(config: AppConfig, settings: Settings) -> AppOverview:
    """Everything about the app that lives in files, plus which prompts have recorded runs."""
    notes: list[str] = []
    try:
        dataset: DatasetInfo | None = _dataset(config)
    except (ConfigError, DataValidationError) as exc:
        dataset, notes = None, [f"Dataset unavailable: {exc}"]
    baselines = [
        _baseline_summary(b.header.name, config) for b in list_baselines(config.baselines_dir)
    ]
    try:
        with history(settings) as repo:
            recorded = repo.prompt_versions(app=config.name)
    except HISTORY_ERRORS as exc:
        recorded = []
        notes.append(f"History database unavailable ({type(exc).__name__}).")
    return AppOverview(
        name=config.name,
        app=config.app,
        prompts=_prompts(config),
        dataset=dataset,
        baselines=baselines,
        recorded_prompt_versions=recorded,
        notes=notes,
    )


def list_runs(
    config: AppConfig,
    settings: Settings,
    *,
    limit: int = 50,
    offset: int = 0,
    prompt_version: str | None = None,
    status: str | None = None,
) -> RunPage:
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)
    with history(settings) as repo:
        records = repo.list_runs(
            app=config.name,
            limit=limit,
            offset=offset,
            prompt_version=prompt_version,
            status=status,
        )
        total = repo.count_matching(app=config.name, prompt_version=prompt_version, status=status)
        ids = [r.run_id for r in records]
        metrics = repo.metric_values(ids, list(HEADLINE_METRICS))
        verdicts = repo.latest_verdicts(ids)
    items = [
        RunSummary(
            run_id=r.run_id,
            prompt_version=r.prompt_version,
            dataset_version=r.dataset_version,
            model=r.model,
            status=r.status,
            trigger=r.trigger,
            started_at=r.started_at,
            cases=r.n_cases,
            api_calls=r.api_calls,
            cache_hits=r.cache_hits,
            metrics=metrics.get(r.run_id, {}),
            verdict=Verdict(verdicts[r.run_id][0]) if r.run_id in verdicts else None,
            verdict_baseline=verdicts[r.run_id][1] if r.run_id in verdicts else None,
        )
        for r in records
    ]
    return RunPage(items=items, total=total, limit=limit, offset=offset)


def _stored_run(settings: Settings, run_id: str) -> RunResult:
    with history(settings) as repo:
        run = repo.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run '{run_id}' is not in the history database")
    return run


def run_detail(config: AppConfig, settings: Settings, run_id: str) -> RunDetail:
    run = _stored_run(settings, run_id)
    if run.meta.app != config.name:
        raise NotFoundError(f"Run '{run_id}' belongs to another app")
    with history(settings) as repo:
        comparisons = repo.comparisons_for(run_id)
    inputs, expected, notes = dataset_context(config, run)
    return RunDetail(
        run=run,
        comparisons=comparisons,
        inputs={k: dict(v) for k, v in inputs.items()},
        expected={k: dict(v) for k, v in expected.items()},
        notes=notes,
    )


def baseline_detail(config: AppConfig, name: str) -> BaselineSummary:
    try:
        return _baseline_summary(name, config)
    except DataValidationError as exc:
        raise NotFoundError(str(exc)) from exc


def compare_runs(
    config: AppConfig,
    settings: Settings,
    candidate_id: str,
    *,
    baseline: str | None = "main",
    against: str | None = None,
    allow_dataset_change: bool = False,
) -> Comparison:
    """Compare on the fly (nothing is saved): against another run, or a named baseline."""
    candidate = _stored_run(settings, candidate_id)
    if against is not None:
        reference, name = _stored_run(settings, against), None
    elif baseline is not None:
        try:
            reference, name = load_baseline(config.baselines_dir, baseline).run, baseline
        except DataValidationError as exc:
            raise NotFoundError(str(exc)) from exc
    else:
        raise NotFoundError("Give a baseline name or a run id to compare against")
    return compare(
        reference,
        candidate,
        config.gate,
        baseline_name=name,
        allow_dataset_change=allow_dataset_change,
    )


def trend(
    config: AppConfig,
    settings: Settings,
    metric: str,
    *,
    prompt_version: str | None = None,
    limit: int = 100,
) -> list[TrendPoint]:
    limit = max(1, min(limit, MAX_TREND_POINTS))
    with history(settings) as repo:
        series = repo.metric_series(
            metric, app=config.name, limit=limit, prompt_version=prompt_version
        )
    return [
        TrendPoint(
            run_id=r.run_id,
            started_at=r.started_at,
            prompt_version=r.prompt_version,
            value=value,
            fresh=r.cache_hits == 0 and r.api_calls > 0,
        )
        for r, value in series
    ]


def drift(config: AppConfig, settings: Settings, *, baseline: str = "main") -> DriftReport:
    try:
        reference = load_baseline(config.baselines_dir, baseline).run
    except DataValidationError as exc:
        raise NotFoundError(str(exc)) from exc
    with history(settings) as repo:
        runs = repo.load_runs(app=config.name)
    return drift_report(reference, runs, config.gate, baseline_name=baseline)
