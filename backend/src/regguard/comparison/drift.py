"""Drift detection over the history of comparable runs. Pure (no I/O).

The baseline gate compares one run with one baseline: it catches changes *we* make.
Drift catches what happens when nothing in our repository changed: the provider updating
the model behind the same name, or quality sliding a little at a time.

Only *comparable fresh* runs count:
- comparable: same app, prompt hash, dataset hash, set of cases and model as the baseline
  (and, for judge scores, the same judge). Any change there is a change we made; the
  baseline gate handles it, and the drift series simply restarts.
- fresh: the run made real API calls for every case (no cache hits). A cached run replays
  old answers and says nothing about today's model.

Rule (per metric): DRIFT when the moving average of the last ``window`` runs is worse than
the baseline value by at least the metric's warn threshold AND each of the last
``consecutive`` runs is worse by that much too. ``new_episode`` is True only when the
previous run was not already drifting, so alerts fire once per episode.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from regguard.comparison.thresholds import crossed, delta, fmt_delta
from regguard.core.gating import DriftConfig, GateConfig, MetricThreshold
from regguard.core.types import DriftReport, DriftStatus, MetricDrift, RunResult, RunStatus
from regguard.metrics.judge import JUDGE_METRIC

_JUDGE_IDENTITY = ("model", "prompt_hash")


def run_key(run: RunResult) -> tuple[object, ...]:
    """What must be identical for two runs' metrics to be comparable over time."""
    m = run.meta
    cases = tuple(sorted({c.case_id for c in run.cases}))
    return (m.app, m.prompt_hash, m.dataset_hash, m.model, cases)


def judge_key(run: RunResult) -> tuple[object, ...] | None:
    judge = run.meta.judge
    return None if judge is None else tuple(judge.get(k) for k in _JUDGE_IDENTITY)


def is_fresh(run: RunResult) -> bool:
    return run.meta.execution.cache_hits == 0 and run.meta.execution.api_calls > 0


def _evaluate(
    values: Sequence[float], reference: float, threshold: MetricThreshold, config: DriftConfig
) -> tuple[DriftStatus, float | None, float | None, int]:
    """(status, moving average, its delta vs reference, worse streak) for one series."""
    window = list(values)[-config.window :]
    if len(window) < config.consecutive:
        return DriftStatus.INSUFFICIENT, None, None, 0
    average = sum(window) / len(window)
    average_delta = delta(reference, average, threshold.unit)

    def worse(value: float) -> bool:
        change = delta(reference, value, threshold.unit)
        return change is not None and crossed(change, threshold.warn)

    streak = 0
    for value in reversed(window):
        if not worse(value):
            break
        streak += 1
    drifting = (
        average_delta is not None
        and crossed(average_delta, threshold.warn)
        and streak >= config.consecutive
    )
    return (DriftStatus.DRIFT if drifting else DriftStatus.OK), average, average_delta, streak


def metric_drift(
    metric: str,
    values: Sequence[float],
    reference: float,
    threshold: MetricThreshold,
    config: DriftConfig,
) -> MetricDrift:
    """Drift status of one metric's series (oldest -> newest, comparable fresh runs only)."""
    values = list(values)
    status, average, average_delta, streak = _evaluate(values, reference, threshold, config)
    window = values[-config.window :]
    new_episode = False
    if status is DriftStatus.DRIFT:
        previous, *_ = _evaluate(values[:-1], reference, threshold, config)
        new_episode = previous is not DriftStatus.DRIFT
    if status is DriftStatus.INSUFFICIENT:
        message = f"insufficient history: {len(values)} of {config.consecutive} runs needed"
    else:
        message = (
            f"moving average {average:.3f} vs baseline {reference:.3f} "
            f"({fmt_delta(average_delta, threshold.unit)}) over {len(window)} run(s); "
            f"last {streak} run(s) worse than the warn threshold"
        )
    return MetricDrift(
        metric=metric,
        status=status,
        reference=reference,
        moving_average=average,
        delta=average_delta,
        unit=threshold.unit,
        runs=len(window),
        worse_streak=streak,
        new_episode=new_episode,
        values=window,
        message=message,
    )


def drift_report(
    baseline: RunResult,
    history: Sequence[RunResult],
    gate: GateConfig,
    *,
    baseline_name: str | None = None,
    now: datetime | None = None,
) -> DriftReport:
    """Check every configured drift metric of ``baseline`` against the run history."""
    key = run_key(baseline)
    comparable = sorted(
        (
            r
            for r in history
            if r.status is RunStatus.COMPLETED
            and r.meta.run_id != baseline.meta.run_id
            and run_key(r) == key
        ),
        key=lambda r: r.meta.started_at,
    )
    fresh = [r for r in comparable if is_fresh(r)]
    notes: list[str] = []
    if len(comparable) > len(fresh):
        notes.append(
            f"{len(comparable) - len(fresh)} comparable run(s) used the response cache and "
            "were ignored; monitoring runs need --cache refresh"
        )

    results: list[MetricDrift] = []
    for metric in gate.drift.metrics:
        threshold = gate.threshold_for(metric)
        reference = baseline.aggregates.get(metric)
        if threshold is None or threshold.warn is None or reference is None:
            continue
        series = fresh
        if metric == JUDGE_METRIC:
            series = [r for r in fresh if judge_key(r) == judge_key(baseline)]
            if len(series) < len(fresh):
                notes.append(
                    f"{len(fresh) - len(series)} run(s) used a different judge and were "
                    f"ignored for {JUDGE_METRIC}"
                )
        values = [r.aggregates[metric].value for r in series if metric in r.aggregates]
        drift = metric_drift(metric, values, reference.value, threshold, gate.drift)
        results.append(drift.model_copy(update={"gating": threshold.gating}))

    # Only gating metrics decide the report status; report-only ones are shown, never alerted.
    statuses = {m.status for m in results if m.gating}
    if DriftStatus.DRIFT in statuses:
        status = DriftStatus.DRIFT
    elif not results or statuses == {DriftStatus.INSUFFICIENT}:
        status = DriftStatus.INSUFFICIENT
    else:
        status = DriftStatus.OK
    return DriftReport(
        app=baseline.meta.app,
        baseline_run_id=baseline.meta.run_id,
        baseline_name=baseline_name,
        status=status,
        comparable_runs=len(comparable),
        fresh_runs=len(fresh),
        latest_run_id=fresh[-1].meta.run_id if fresh else None,
        metrics=results,
        notes=notes,
        created_at=now or datetime.now(UTC),
    )
