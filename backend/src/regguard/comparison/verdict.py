"""Compare a candidate run with a baseline run and decide PASS / WARN / FAIL. Pure function.

Rules (ADR 0003):
- FAIL: a gated metric crosses its *critical* threshold AND there is evidence: the exact
  one-sided McNemar test (rates) or sign test (per-case values) is significant
  (p < alpha) OR at least ``min_regressed_cases`` paired cases regressed. Run-level
  aggregates (tokens, latency, macro-F1) have no pairing, so crossing critical is enough.
- FAIL (hard rules): candidate schema validity below the floor; a ``critical`` case regressed.
- WARN: a gated metric crosses *warn*, or crosses *critical* without enough evidence
  ("underpowered"); or the dataset changed between the two runs.
- PASS: otherwise.
Infrastructure failures are never quality verdicts: an ERROR candidate gives ``Verdict.ERROR``.
"""

from collections import Counter
from datetime import UTC, datetime

from regguard.comparison.diff import (
    Paired,
    case_labels,
    case_outcomes,
    diff_cases,
    mean_tokens,
    paired_ids,
    paired_rate,
    paired_values,
)
from regguard.comparison.stats import mcnemar_one_sided, min_regressions_for_significance
from regguard.core.errors import ComparisonError
from regguard.core.gating import GateConfig, MetricThreshold
from regguard.core.types import (
    CaseChange,
    Comparison,
    MetricDelta,
    MetricKind,
    Reason,
    RunResult,
    RunStatus,
    Severity,
    ThresholdLevel,
    Verdict,
)
from regguard.metrics.judge import JUDGE_METRIC

_EPS = 1e-9  # so that e.g. exactly -3 points counts as crossing a -0.03 threshold
_PASS_RATE = "pass_rate"  # noqa: S105 - a metric name, not a password
_AGGREGATE_ONLY = ("latency_ms_p50", "latency_ms_p95", "macro_f1")


def _crossed(delta: float, threshold: float | None) -> bool:
    if threshold is None:
        return False
    return delta <= threshold + _EPS if threshold < 0 else delta >= threshold - _EPS


def _level(delta: float | None, threshold: MetricThreshold | None) -> ThresholdLevel:
    if delta is None or threshold is None:
        return ThresholdLevel.OK
    if _crossed(delta, threshold.critical):
        return ThresholdLevel.CRITICAL
    if _crossed(delta, threshold.warn):
        return ThresholdLevel.WARN
    return ThresholdLevel.OK


def _delta(baseline: float, candidate: float, unit: str) -> float | None:
    if unit == "absolute":
        return candidate - baseline
    return (candidate - baseline) / baseline if baseline else None


def _fmt_delta(delta: float | None, unit: str) -> str:
    if delta is None:
        return "n/a"
    return f"{delta * 100:+.1f} pts" if unit == "absolute" else f"{delta * 100:+.0f}%"


def _fmt_value(value: float, kind: MetricKind) -> str:
    if kind is MetricKind.RATE:
        return f"{value:.1%}"
    return f"{value:.2f}" if abs(value) < 10 else f"{value:.0f}"


def _verdict(reasons: list[Reason]) -> Verdict:
    severities = {r.severity for r in reasons}
    if Severity.FAIL in severities:
        return Verdict.FAIL
    if Severity.WARN in severities:
        return Verdict.WARN
    return Verdict.PASS


class _Builder:
    """Accumulates metric rows and reasons for one comparison."""

    def __init__(self, gate: GateConfig) -> None:
        self.gate = gate
        self.metrics: list[MetricDelta] = []
        self.reasons: list[Reason] = []

    def paired(self, name: str, kind: MetricKind, p: Paired) -> None:
        """A metric measured per case in both runs: evidence = exact test or enough flips."""
        threshold = self.gate.threshold_for(name)
        unit = threshold.unit if threshold else "absolute"
        delta = _delta(p.baseline, p.candidate, unit)
        level = _level(delta, threshold)
        p_value = mcnemar_one_sided(p.regressed, p.improved)
        gating = threshold.gating if threshold else False
        self.metrics.append(
            MetricDelta(
                metric=name,
                kind=kind,
                baseline=p.baseline,
                candidate=p.candidate,
                delta=delta,
                unit=unit,
                n=p.n,
                regressed=p.regressed,
                improved=p.improved,
                p_value=p_value,
                level=level,
                gating=gating,
            )
        )
        if level is ThresholdLevel.OK:
            return
        change = (
            f"{name} {_fmt_value(p.baseline, kind)} -> {_fmt_value(p.candidate, kind)} "
            f"({_fmt_delta(delta, unit)}), {p.regressed} regressed / {p.improved} improved "
            f"of {p.n}, p={p_value:.3f}"
        )
        if not gating:
            self.add("threshold_crossed_info", Severity.INFO, f"{change} (not gating)", name)
        elif level is ThresholdLevel.WARN:
            self.add("warn_regression", Severity.WARN, change, name)
        elif p_value < self.gate.alpha or p.regressed >= self.gate.min_regressed_cases:
            self.add("critical_regression", Severity.FAIL, change, name)
        else:
            self.add(
                "critical_underpowered",
                Severity.WARN,
                f"{change}: beyond the critical threshold but not enough evidence (needs "
                f"p < {self.gate.alpha} or >= {self.gate.min_regressed_cases} regressed cases)",
                name,
            )

    def aggregate(self, name: str, baseline: float, candidate: float, n: int) -> None:
        """A run-level number with no per-case pairing: crossing critical is enough."""
        kind = MetricKind.AGGREGATE
        threshold = self.gate.threshold_for(name)
        unit = threshold.unit if threshold else "relative"
        delta = _delta(baseline, candidate, unit)
        level = _level(delta, threshold)
        gating = threshold.gating if threshold else False
        self.metrics.append(
            MetricDelta(
                metric=name,
                kind=kind,
                baseline=baseline,
                candidate=candidate,
                delta=delta,
                unit=unit,
                n=n,
                level=level,
                gating=gating,
            )
        )
        if level is ThresholdLevel.OK:
            return
        change = (
            f"{name} {_fmt_value(baseline, kind)} -> {_fmt_value(candidate, kind)} "
            f"({_fmt_delta(delta, unit)})"
        )
        if not gating:
            self.add("threshold_crossed_info", Severity.INFO, f"{change} (not gating)", name)
        elif level is ThresholdLevel.WARN:
            self.add("warn_regression", Severity.WARN, change, name)
        else:
            self.add("critical_regression", Severity.FAIL, change, name)

    def add(self, code: str, severity: Severity, message: str, metric: str | None = None) -> None:
        self.reasons.append(Reason(code=code, severity=severity, message=message, metric=metric))


_JUDGE_IDENTITY = ("model", "prompt_hash")


def _judge_change(baseline: RunResult, candidate: RunResult) -> str | None:
    """Describe how the judge differs between the two runs, or None if it is the same judge."""
    b, c = baseline.meta.judge or {}, candidate.meta.judge or {}
    changed = [key for key in _JUDGE_IDENTITY if b.get(key) != c.get(key)]
    if not changed:
        return None
    b_name = f"{b.get('prompt_version', '?')} / {b.get('model', '?')}"
    c_name = f"{c.get('prompt_version', '?')} / {c.get('model', '?')}"
    return f"baseline {b_name}, candidate {c_name}"


def _check_comparable(
    baseline: RunResult, candidate: RunResult, allow_dataset_change: bool
) -> None:
    b, c = baseline.meta, candidate.meta
    if b.app != c.app:
        raise ComparisonError(
            f"Runs belong to different apps: baseline '{b.app}', candidate '{c.app}'"
        )
    if baseline.status is not RunStatus.COMPLETED:
        raise ComparisonError(f"Baseline run {b.run_id} has status {baseline.status.value}")
    if b.dataset_hash != c.dataset_hash and not allow_dataset_change:
        raise ComparisonError(
            f"Dataset changed: baseline used {b.dataset_version} ({b.dataset_hash[:19]}), "
            f"candidate used {c.dataset_version} ({c.dataset_hash[:19]}). Promote a new baseline "
            "on the new dataset, or pass --allow-dataset-change to compare the shared cases only."
        )


def compare(
    baseline: RunResult,
    candidate: RunResult,
    gate: GateConfig,
    *,
    baseline_name: str | None = None,
    allow_dataset_change: bool = False,
    now: datetime | None = None,
) -> Comparison:
    _check_comparable(baseline, candidate, allow_dataset_change)
    shell = Comparison(
        app=candidate.meta.app,
        baseline_run_id=baseline.meta.run_id,
        baseline_name=baseline_name,
        candidate_run_id=candidate.meta.run_id,
        verdict=Verdict.ERROR,
        gate=gate.model_dump(mode="json"),
        created_at=now or datetime.now(UTC),
    )

    if candidate.status is not RunStatus.COMPLETED:
        reason = Reason(
            code="candidate_error",
            severity=Severity.FAIL,
            message=f"Candidate run is {candidate.status.value}: {candidate.error or 'unknown'}. "
            "Infrastructure failures are not quality regressions; fix and rerun.",
        )
        return shell.model_copy(update={"reasons": [reason]})

    base, cand = case_outcomes(baseline), case_outcomes(candidate)
    labels = {**case_labels(baseline), **case_labels(candidate)}
    critical = set(baseline.meta.critical_case_ids) | set(candidate.meta.critical_case_ids)
    cases = diff_cases(base, cand, labels=labels, critical=critical)
    ids = paired_ids(base, cand)
    overall = paired_rate(base, cand, ids, None)
    if not ids or overall is None:
        raise ComparisonError("The two runs have no successfully evaluated cases in common")

    builder = _Builder(gate)
    if baseline.meta.dataset_hash != candidate.meta.dataset_hash:
        builder.add(
            "dataset_changed",
            Severity.WARN,
            f"Dataset changed ({baseline.meta.dataset_version} -> "
            f"{candidate.meta.dataset_version}); only the {len(ids)} shared case(s) were compared",
        )

    # Per-case metrics on paired cases: overall pass, each binary metric, per-label slices,
    # then continuous per-case values (similarity, judge score).
    builder.paired(_PASS_RATE, MetricKind.RATE, overall)
    binary_names = sorted(
        {m for i in ids for m in base[i].metrics} & {m for i in ids for m in cand[i].metrics}
    )
    for metric in binary_names:
        if (p := paired_rate(base, cand, ids, metric)) is not None:
            builder.paired(metric, MetricKind.RATE, p)
    for metric in binary_names:
        for label in sorted({labels[i] for i in ids if i in labels}):
            name = f"{metric}/{label}"
            if gate.threshold_for(name) is not None:
                in_slice = {i for i in ids if labels.get(i) == label}
                if (p := paired_rate(base, cand, in_slice, metric)) is not None:
                    builder.paired(name, MetricKind.RATE, p)
    value_names = sorted(
        {m for i in ids for m in base[i].values} & {m for i in ids for m in cand[i].values}
    )
    if JUDGE_METRIC in value_names and (change := _judge_change(baseline, candidate)):
        # Scores from different judges are on different scales: comparing them would show a
        # "regression" or "improvement" caused by the judge, not by the app.
        value_names.remove(JUDGE_METRIC)
        threshold = gate.threshold_for(JUDGE_METRIC)
        severity = Severity.WARN if threshold and threshold.gating else Severity.INFO
        builder.add(
            "judge_changed",
            severity,
            f"{JUDGE_METRIC} not compared: the runs were graded by different judges ({change}). "
            "Re-run the baseline with the current judge (app calls are cached) and promote it.",
            JUDGE_METRIC,
        )
    for metric in value_names:
        threshold = gate.threshold_for(metric)
        epsilon = threshold.epsilon if threshold else 0.0
        if (p := paired_values(base, cand, ids, metric, epsilon=epsilon)) is not None:
            builder.paired(metric, MetricKind.VALUE, p)

    # Run-level aggregates: latency (fresh calls only), macro-F1, tokens per paired case.
    for key in _AGGREGATE_ONLY:
        if key in baseline.aggregates and key in candidate.aggregates:
            b_agg, c_agg = baseline.aggregates[key], candidate.aggregates[key]
            builder.aggregate(key, b_agg.value, c_agg.value, c_agg.n)
    b_tokens, c_tokens = mean_tokens(base, ids), mean_tokens(cand, ids)
    if b_tokens is not None and c_tokens is not None:
        builder.aggregate("tokens_per_case", b_tokens, c_tokens, len(ids))

    # Hard rules.
    schema = candidate.aggregates.get("schema_valid")
    floor = gate.schema_valid_floor
    if floor is not None and schema is not None and schema.value < floor:
        builder.add(
            "schema_valid_floor",
            Severity.FAIL,
            f"schema_valid {schema.value:.1%} is below the floor of {floor:.0%}",
            "schema_valid",
        )
    if gate.critical_cases_must_not_regress:
        for d in cases:
            if d.critical and d.change is CaseChange.REGRESSED:
                builder.add(
                    "critical_case_regressed",
                    Severity.FAIL,
                    f"Critical case {d.case_id} regressed "
                    f"(now failing: {', '.join(d.candidate_failed_metrics) or 'pass'})",
                )

    counts = Counter(d.change.value for d in cases)
    not_compared = counts[CaseChange.NEW.value] + counts[CaseChange.REMOVED.value]
    skipped = counts[CaseChange.SKIPPED.value]
    if not_compared or skipped:
        builder.add(
            "cases_not_compared",
            Severity.INFO,
            f"{counts[CaseChange.NEW.value]} new, {counts[CaseChange.REMOVED.value]} removed and "
            f"{skipped} errored case(s) were not compared",
        )
    needed = min_regressions_for_significance(gate.alpha)
    builder.add(
        "statistical_power",
        Severity.INFO,
        f"{len(ids)} paired case(s): one case = {100 / len(ids):.1f} points; at least {needed} "
        f"one-way regressions are needed for significance at alpha={gate.alpha}",
    )

    return shell.model_copy(
        update={
            "verdict": _verdict(builder.reasons),
            "reasons": builder.reasons,
            "metrics": builder.metrics,
            "cases": cases,
            "counts": dict(counts),
        }
    )
