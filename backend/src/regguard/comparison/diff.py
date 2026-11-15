"""Pair the cases of two runs and count what changed. Pure functions.

A *case outcome* collapses a case's samples (``n_samples`` >= 1) into one result:
- any sample with an infrastructure error -> the case is skipped (never a quality signal);
- otherwise pass/fail by strict majority of samples (a tie counts as fail).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from regguard.core.types import CaseChange, CaseDiff, CaseResult, RunResult


@dataclass(frozen=True)
class CaseOutcome:
    passed: bool | None  # None: errored in at least one sample -> skipped
    metrics: dict[str, bool] = field(default_factory=dict)  # binary metric -> passed
    values: dict[str, float] = field(default_factory=dict)  # continuous metric -> mean value
    tokens: float | None = None  # mean total tokens per sample


@dataclass(frozen=True)
class Paired:
    """A metric measured on the same cases in both runs (rate for binary, mean for values)."""

    baseline: float
    candidate: float
    n: int
    regressed: int  # pass -> fail, or value dropped by more than epsilon
    improved: int  # fail -> pass, or value rose by more than epsilon


def _majority(values: list[bool]) -> bool:
    return sum(values) * 2 > len(values)


def case_outcomes(run: RunResult) -> dict[str, CaseOutcome]:
    grouped: dict[str, list[CaseResult]] = defaultdict(list)
    for result in run.cases:
        grouped[result.case_id].append(result)

    outcomes: dict[str, CaseOutcome] = {}
    for case_id, samples in grouped.items():
        if any(s.error is not None for s in samples):
            outcomes[case_id] = CaseOutcome(passed=None)
            continue
        per_metric: dict[str, list[bool]] = defaultdict(list)
        per_value: dict[str, list[float]] = defaultdict(list)
        for sample in samples:
            for score in sample.scores:
                if score.passed is not None:
                    per_metric[score.name].append(score.passed)
                else:
                    per_value[score.name].append(score.value)
        tokens = [float(s.usage.total_tokens) for s in samples if s.usage is not None]
        outcomes[case_id] = CaseOutcome(
            passed=_majority([s.passed for s in samples]),
            metrics={name: _majority(values) for name, values in per_metric.items()},
            values={name: sum(v) / len(v) for name, v in per_value.items()},
            tokens=sum(tokens) / len(tokens) if tokens else None,
        )
    return outcomes


def case_labels(run: RunResult) -> dict[str, str]:
    """Golden label per case: from run metadata, or (older runs) from score details."""
    if run.meta.case_labels:
        return dict(run.meta.case_labels)
    labels: dict[str, str] = {}
    for result in run.cases:
        for score in result.scores:
            expected = score.detail.get("expected")
            if isinstance(expected, str):
                labels[result.case_id] = expected
    return labels


def paired_ids(
    baseline: Mapping[str, CaseOutcome], candidate: Mapping[str, CaseOutcome]
) -> set[str]:
    """Cases present in both runs with no infrastructure error in either."""
    return {
        case_id
        for case_id in baseline.keys() & candidate.keys()
        if baseline[case_id].passed is not None and candidate[case_id].passed is not None
    }


def _failed(outcome: CaseOutcome | None) -> tuple[str, ...]:
    if outcome is None or outcome.passed is None:
        return ()
    return tuple(sorted(name for name, ok in outcome.metrics.items() if not ok))


def _change(base: CaseOutcome | None, cand: CaseOutcome | None) -> CaseChange:
    if base is None:
        return CaseChange.NEW
    if cand is None:
        return CaseChange.REMOVED
    if base.passed is None or cand.passed is None:
        return CaseChange.SKIPPED
    if base.passed and not cand.passed:
        return CaseChange.REGRESSED
    if cand.passed and not base.passed:
        return CaseChange.IMPROVED
    return CaseChange.STILL_PASS if cand.passed else CaseChange.STILL_FAIL


def diff_cases(
    baseline: Mapping[str, CaseOutcome],
    candidate: Mapping[str, CaseOutcome],
    *,
    labels: Mapping[str, str],
    critical: Iterable[str],
) -> list[CaseDiff]:
    critical_ids = set(critical)
    diffs = []
    for case_id in sorted(baseline.keys() | candidate.keys()):
        base, cand = baseline.get(case_id), candidate.get(case_id)
        diffs.append(
            CaseDiff(
                case_id=case_id,
                change=_change(base, cand),
                label=labels.get(case_id),
                critical=case_id in critical_ids,
                baseline_failed_metrics=_failed(base),
                candidate_failed_metrics=_failed(cand),
            )
        )
    return diffs


def paired_rate(
    baseline: Mapping[str, CaseOutcome],
    candidate: Mapping[str, CaseOutcome],
    case_ids: Iterable[str],
    metric: str | None = None,
) -> Paired | None:
    """Pass rate of ``metric`` (None = the case's overall pass) on the given paired cases."""
    pairs: list[tuple[bool, bool]] = []
    for case_id in case_ids:
        base, cand = baseline[case_id], candidate[case_id]
        if metric is None:
            if base.passed is not None and cand.passed is not None:
                pairs.append((base.passed, cand.passed))
        elif metric in base.metrics and metric in cand.metrics:
            pairs.append((base.metrics[metric], cand.metrics[metric]))
    if not pairs:
        return None
    n = len(pairs)
    return Paired(
        baseline=sum(b for b, _ in pairs) / n,
        candidate=sum(c for _, c in pairs) / n,
        n=n,
        regressed=sum(1 for b, c in pairs if b and not c),
        improved=sum(1 for b, c in pairs if c and not b),
    )


def paired_values(
    baseline: Mapping[str, CaseOutcome],
    candidate: Mapping[str, CaseOutcome],
    case_ids: Iterable[str],
    metric: str,
    *,
    epsilon: float = 0.0,
) -> Paired | None:
    """Mean of a continuous ``metric``; a case regressed/improved if it moved by > epsilon."""
    pairs = [
        (baseline[i].values[metric], candidate[i].values[metric])
        for i in case_ids
        if metric in baseline[i].values and metric in candidate[i].values
    ]
    if not pairs:
        return None
    n = len(pairs)
    return Paired(
        baseline=sum(b for b, _ in pairs) / n,
        candidate=sum(c for _, c in pairs) / n,
        n=n,
        regressed=sum(1 for b, c in pairs if b - c > epsilon),
        improved=sum(1 for b, c in pairs if c - b > epsilon),
    )


def mean_tokens(outcomes: Mapping[str, CaseOutcome], case_ids: Iterable[str]) -> float | None:
    values = [t for i in case_ids if (t := outcomes[i].tokens) is not None]
    return sum(values) / len(values) if values else None
