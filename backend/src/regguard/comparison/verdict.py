"""Compare a candidate run with a baseline run and decide PASS / WARN / FAIL. Pure function.

Rules (ADR 0003):
- FAIL: a gated metric crosses its *critical* threshold AND there is evidence: the exact
  one-sided McNemar test is significant (p < alpha) OR at least ``min_regressed_cases``
  paired cases regressed. Continuous metrics (tokens, latency) have no paired test, so
  crossing critical is enough.
- FAIL (hard rules): candidate schema validity below the floor; a ``critical`` case regressed.
- WARN: a gated metric crosses *warn*, or crosses *critical* without enough evidence
  ("underpowered"); or the dataset changed between the two runs.
- PASS: otherwise.
Infrastructure failures are never quality verdicts: an ERROR candidate gives ``Verdict.ERROR``.
"""

from collections import Counter
from datetime import UTC, datetime

from regguard.comparison.diff import (
    CaseOutcome,
    case_labels,
    case_outcomes,
    diff_cases,
    mean_tokens,
    paired_ids,
    paired_rate,
)
from regguard.comparison.stats import mcnemar_one_sided, min_regressions_for_significance
from regguard.core.errors import ComparisonError
from regguard.core.gating import GateConfig, MetricThreshold
from regguard.core.types import (
    CaseChange,
    Comparison,
    MetricDelta,
    Reason,
    RunResult,
    RunStatus,
    Severity,
    ThresholdLevel,
    Verdict,
)

_EPS = 1e-9  # so that e.g. exactly -3 points counts as crossing a -0.03 threshold
_PASS_RATE = "pass_rate"  # noqa: S105 - a metric name, not a password
_CONTINUOUS = ("latency_ms_p50", "latency_ms_p95")


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

    def binary(
        self,
        name: str,
        base: dict[str, CaseOutcome],
        cand: dict[str, CaseOutcome],
        ids: set[str],
        metric: str | None,
    ) -> None:
        rate = paired_rate(base, cand, ids, metric)
        if rate is None:
            return
        threshold = self.gate.threshold_for(name)
        unit = threshold.unit if threshold else "absolute"
        delta = _delta(rate.baseline, rate.candidate, unit)
        level = _level(delta, threshold)
        p_value = mcnemar_one_sided(rate.regressed, rate.improved)
        gating = threshold.gating if threshold else False
        self.metrics.append(
            MetricDelta(
                metric=name,
                baseline=rate.baseline,
                candidate=rate.candidate,
                delta=delta,
                unit=unit,
                n=rate.n,
                regressed=rate.regressed,
                improved=rate.improved,
                p_value=p_value,
                level=level,
                gating=gating,
            )
        )
        if level is ThresholdLevel.OK:
            return
        change = (
            f"{name} {rate.baseline:.1%} -> {rate.candidate:.1%} ({_fmt_delta(delta, unit)}), "
            f"{rate.regressed} regressed / {rate.improved} improved of {rate.n}, p={p_value:.3f}"
        )
        if not gating:
            self.add("threshold_crossed_info", Severity.INFO, f"{change} (not gating)", name)
        elif level is ThresholdLevel.WARN:
            self.add("warn_regression", Severity.WARN, change, name)
        elif p_value < self.gate.alpha or rate.regressed >= self.gate.min_regressed_cases:
            self.add("critical_regression", Severity.FAIL, change, name)
        else:
            self.add(
                "critical_underpowered",
                Severity.WARN,
                f"{change}: beyond the critical threshold but not enough evidence (needs "
                f"p < {self.gate.alpha} or >= {self.gate.min_regressed_cases} regressed cases)",
                name,
            )

    def continuous(self, name: str, baseline: float, candidate: float, n: int) -> None:
        threshold = self.gate.threshold_for(name)
        unit = threshold.unit if threshold else "relative"
        delta = _delta(baseline, candidate, unit)
        level = _level(delta, threshold)
        gating = threshold.gating if threshold else False
        self.metrics.append(
            MetricDelta(
                metric=name,
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
        change = f"{name} {baseline:.0f} -> {candidate:.0f} ({_fmt_delta(delta, unit)})"
        if not gating:
            self.add("threshold_crossed_info", Severity.INFO, f"{change} (not gating)", name)
        elif level is ThresholdLevel.WARN:
            self.add("warn_regression", Severity.WARN, change, name)
        else:
            self.add("critical_regression", Severity.FAIL, change, name)

    def add(self, code: str, severity: Severity, message: str, metric: str | None = None) -> None:
        self.reasons.append(Reason(code=code, severity=severity, message=message, metric=metric))


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
    if not ids:
        raise ComparisonError("The two runs have no successfully evaluated cases in common")

    builder = _Builder(gate)
    if baseline.meta.dataset_hash != candidate.meta.dataset_hash:
        builder.add(
            "dataset_changed",
            Severity.WARN,
            f"Dataset changed ({baseline.meta.dataset_version} -> "
            f"{candidate.meta.dataset_version}); only the {len(ids)} shared case(s) were compared",
        )

    # Binary metrics on paired cases: overall pass, each metric, then per-label slices.
    builder.binary(_PASS_RATE, base, cand, ids, None)
    metric_names = sorted(
        {m for i in ids for m in base[i].metrics} & {m for i in ids for m in cand[i].metrics}
    )
    for metric in metric_names:
        builder.binary(metric, base, cand, ids, metric)
    for metric in metric_names:
        for label in sorted({labels[i] for i in ids if i in labels}):
            name = f"{metric}/{label}"
            if gate.threshold_for(name) is not None:
                in_slice = {i for i in ids if labels.get(i) == label}
                builder.binary(name, base, cand, in_slice, metric)

    # Continuous metrics: latency (fresh calls only, from each run), tokens per paired case.
    for key in _CONTINUOUS:
        if key in baseline.aggregates and key in candidate.aggregates:
            b_agg, c_agg = baseline.aggregates[key], candidate.aggregates[key]
            builder.continuous(key, b_agg.value, c_agg.value, c_agg.n)
    b_tokens, c_tokens = mean_tokens(base, ids), mean_tokens(cand, ids)
    if b_tokens is not None and c_tokens is not None:
        builder.continuous("tokens_per_case", b_tokens, c_tokens, len(ids))

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
