"""Drift detection over run history (pure)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from regguard.comparison.drift import drift_report, metric_drift, run_key
from regguard.core.gating import DriftConfig, GateConfig, MetricThreshold
from regguard.core.types import (
    AggregateScore,
    DriftStatus,
    ExecutionStats,
    RunResult,
    RunStatus,
)
from tests.unit.run_factory import make_run, outcomes

CONFIG = DriftConfig()  # window 7, consecutive 3
LABEL = MetricThreshold(warn=-0.03, critical=-0.08)  # the label_exact default
T0 = datetime(2026, 11, 1, tzinfo=UTC)


# --- one metric ---------------------------------------------------------------------------


def test_stable_series_is_ok() -> None:
    d = metric_drift("label_exact", [0.9, 0.91, 0.89, 0.9], 0.9, LABEL, CONFIG)
    assert d.status is DriftStatus.OK
    assert d.moving_average == pytest.approx(0.9)
    assert d.worse_streak == 0


def test_sustained_drop_is_drift_and_a_new_episode() -> None:
    d = metric_drift("label_exact", [0.9, 0.9, 0.8, 0.8, 0.8], 0.9, LABEL, CONFIG)
    assert d.status is DriftStatus.DRIFT
    assert d.worse_streak == 3
    assert d.delta == pytest.approx(-0.06)
    assert d.new_episode is True


def test_continuing_drift_is_not_a_new_episode() -> None:
    d = metric_drift("label_exact", [0.9, 0.9, 0.8, 0.8, 0.8, 0.8], 0.9, LABEL, CONFIG)
    assert d.status is DriftStatus.DRIFT
    assert d.new_episode is False  # already drifting at the previous run: alert only once


def test_one_bad_run_is_not_drift() -> None:
    d = metric_drift("label_exact", [0.9, 0.9, 0.9, 0.5], 0.9, LABEL, CONFIG)
    assert d.status is DriftStatus.OK  # average is down, but only 1 consecutive bad run
    assert d.worse_streak == 1


def test_recovery_ends_the_episode() -> None:
    d = metric_drift("label_exact", [0.8, 0.8, 0.8, 0.9], 0.9, LABEL, CONFIG)
    assert d.status is DriftStatus.OK
    assert d.worse_streak == 0


def test_bad_runs_outside_the_window_are_forgotten() -> None:
    old_bad = [0.5] * 5
    d = metric_drift("label_exact", [*old_bad, *[0.9] * 7], 0.9, LABEL, CONFIG)
    assert d.status is DriftStatus.OK
    assert d.runs == 7
    assert d.values == [0.9] * 7


def test_too_few_runs_is_insufficient_not_ok() -> None:
    d = metric_drift("label_exact", [0.5, 0.5], 0.9, LABEL, CONFIG)
    assert d.status is DriftStatus.INSUFFICIENT
    assert "2 of 3" in d.message


def test_rising_metric_with_positive_relative_threshold() -> None:
    tokens = MetricThreshold(warn=0.20, critical=0.50, unit="relative")
    d = metric_drift("tokens", [100, 130, 130, 130], 100.0, tokens, CONFIG)
    assert d.status is DriftStatus.DRIFT
    assert d.unit == "relative"


def test_consecutive_cannot_exceed_window() -> None:
    with pytest.raises(ValidationError):
        DriftConfig(window=3, consecutive=4)


# --- report over a history of runs ----------------------------------------------------------

BASELINE = make_run(outcomes(12), run_id="base")


def monitored(
    i: int,
    label: float,
    *,
    cached: bool = False,
    status: RunStatus = RunStatus.COMPLETED,
    prompt_hash: str | None = None,
    judge: dict[str, str] | None = None,
    judge_score: float | None = None,
    n_cases: int = 12,
) -> RunResult:
    run = make_run(outcomes(n_cases), run_id=f"run-{i:02d}", status=status)
    aggregates = {
        "label_exact": AggregateScore(value=label, n=n_cases),
        "schema_valid": AggregateScore(value=1.0, n=n_cases),
    }
    if judge_score is not None:
        aggregates["summary_judge"] = AggregateScore(value=judge_score, n=n_cases)
    execution = ExecutionStats(
        api_calls=0 if cached else n_cases, cache_hits=n_cases if cached else 0
    )
    updates: dict[str, object] = {
        "started_at": T0 + timedelta(days=i),
        "execution": execution,
        "judge": judge,
    }
    if prompt_hash is not None:
        updates["prompt_hash"] = prompt_hash
    return run.model_copy(
        update={"meta": run.meta.model_copy(update=updates), "aggregates": aggregates}
    )


def baseline(label: float = 0.9, judge: dict[str, str] | None = None) -> RunResult:
    aggregates = {
        "label_exact": AggregateScore(value=label, n=12),
        "schema_valid": AggregateScore(value=1.0, n=12),
        "summary_judge": AggregateScore(value=4.5, n=12),
    }
    meta = BASELINE.meta.model_copy(update={"judge": judge})
    return BASELINE.model_copy(update={"meta": meta, "aggregates": aggregates})


def metric(report_metrics: list, name: str):  # type: ignore[no-untyped-def,type-arg]
    return next(m for m in report_metrics if m.metric == name)


def test_report_detects_drift_on_fresh_comparable_runs() -> None:
    history = [monitored(i, v) for i, v in enumerate([0.9, 0.9, 0.8, 0.8, 0.8])]
    report = drift_report(baseline(), history, GateConfig(), baseline_name="main")
    assert report.status is DriftStatus.DRIFT
    assert (report.comparable_runs, report.fresh_runs) == (5, 5)
    assert report.latest_run_id == "run-04"
    assert metric(report.metrics, "label_exact").status is DriftStatus.DRIFT
    assert metric(report.metrics, "schema_valid").status is DriftStatus.OK


def test_cached_runs_are_ignored_with_a_note() -> None:
    history = [monitored(i, 0.5, cached=True) for i in range(5)]
    report = drift_report(baseline(), history, GateConfig())
    assert report.status is DriftStatus.INSUFFICIENT
    assert (report.comparable_runs, report.fresh_runs) == (5, 0)
    assert any("--cache refresh" in n for n in report.notes)


@pytest.mark.parametrize(
    "other",
    [
        {"prompt_hash": "sha256:" + "f" * 64},  # a prompt change restarts the series
        {"n_cases": 8},  # a different set of cases is not comparable
        {"status": RunStatus.ERROR},  # failed runs never count
    ],
)
def test_non_comparable_runs_are_excluded(other: dict[str, object]) -> None:
    history = [monitored(i, 0.5, **other) for i in range(5)]  # type: ignore[arg-type]
    report = drift_report(baseline(), history, GateConfig())
    assert report.comparable_runs == 0
    assert report.status is DriftStatus.INSUFFICIENT


def test_the_baseline_run_itself_is_not_in_its_own_window() -> None:
    same = baseline().model_copy(
        update={
            "meta": baseline().meta.model_copy(update={"execution": ExecutionStats(api_calls=12)})
        }
    )
    report = drift_report(baseline(), [same], GateConfig())
    assert report.comparable_runs == 0


def test_judge_scores_only_count_with_the_same_judge() -> None:
    judge_v2 = {"model": "j", "prompt_hash": "sha256:2"}
    judge_v1 = {"model": "j", "prompt_hash": "sha256:1"}
    history = [
        monitored(i, 0.9, judge=judge_v1 if i < 3 else judge_v2, judge_score=3.0) for i in range(6)
    ]
    report = drift_report(baseline(judge=judge_v2), history, GateConfig())
    judge = metric(report.metrics, "summary_judge")
    assert judge.runs == 3  # only the v2-judged runs
    assert any("different judge" in n for n in report.notes)
    # 3.0 vs 4.5 three runs in a row: the judge drifts, but it is report-only by default,
    # so the report (and --fail-on-drift) stays OK.
    assert judge.status is DriftStatus.DRIFT
    assert judge.gating is False
    assert report.status is DriftStatus.OK


def test_gating_judge_drift_makes_the_report_drift() -> None:
    gate = GateConfig(
        metrics={"summary_judge": MetricThreshold(warn=-0.05, unit="relative", gating=True)}
    )
    judge = {"model": "j", "prompt_hash": "sha256:2"}
    history = [monitored(i, 0.9, judge=judge, judge_score=3.0) for i in range(3)]
    assert drift_report(baseline(judge=judge), history, gate).status is DriftStatus.DRIFT


def test_run_key_includes_the_case_set() -> None:
    assert run_key(monitored(1, 0.9)) == run_key(monitored(2, 0.5))
    assert run_key(monitored(1, 0.9)) != run_key(monitored(1, 0.9, n_cases=8))
