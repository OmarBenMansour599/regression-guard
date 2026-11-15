"""Run-level aggregates from per-case results. Pure functions.

Conventions:
- Quality metrics are averaged over cases that did NOT error (infra failures are
  reported via ``error_rate``, never as quality loss).
- Latency percentiles use only fresh (non-cached) calls.
- Per-label slices use the key ``<metric>/<label>`` (``label_exact/<label>`` is that
  label's recall); ``precision/<label>``, ``f1/<label>`` and ``macro_f1`` come from the
  confusion matrix over valid outputs.
- A metric that returned no score for a case (not applicable) is simply absent there.
"""

import math
from collections import defaultdict
from collections.abc import Sequence

from regguard.core.types import AggregateScore, CaseResult
from regguard.datasets.models import GoldenCase
from regguard.metrics.classification import label_stats, macro_f1


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile, q in [0, 100]."""
    if not values:
        raise ValueError("percentile of empty sequence")
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def _mean(values: Sequence[float]) -> AggregateScore:
    return AggregateScore(value=sum(values) / len(values) if values else 0.0, n=len(values))


def compute_aggregates(
    results: Sequence[CaseResult],
    cases: Sequence[GoldenCase],
    *,
    label_field: str | None = None,
) -> dict[str, AggregateScore]:
    total = len(results)
    ok = [r for r in results if r.error is None]
    errored = total - len(ok)
    agg: dict[str, AggregateScore] = {
        "error_rate": AggregateScore(value=errored / total if total else 0.0, n=total),
        "pass_rate": _mean([1.0 if r.passed else 0.0 for r in ok]),
    }

    by_metric: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        for s in r.scores:
            by_metric[s.name].append(s.value)
    for name, values in by_metric.items():
        agg[name] = _mean(values)

    if label_field:
        label_of = {c.id: str(c.expected.get(label_field)) for c in cases}
        sliced: dict[str, list[float]] = defaultdict(list)
        for r in ok:
            for s in r.scores:
                sliced[f"{s.name}/{label_of.get(r.case_id)}"].append(s.value)
        for key, values in sorted(sliced.items()):
            agg[key] = _mean(values)

        pairs = [
            (label_of[r.case_id], str(r.parsed_output[label_field]))
            for r in ok
            if r.parsed_output is not None and label_field in r.parsed_output
        ]
        if pairs:
            stats = label_stats(pairs)
            for st in stats:
                agg[f"precision/{st.label}"] = AggregateScore(value=st.precision, n=st.tp + st.fp)
                agg[f"f1/{st.label}"] = AggregateScore(value=st.f1, n=st.support)
            agg["macro_f1"] = AggregateScore(value=macro_f1(stats), n=len(pairs))

    judged = [r.judge for r in ok if r.judge is not None]
    if judged:
        failed = sum(1 for j in judged if j.error is not None)
        agg["judge_error_rate"] = AggregateScore(value=failed / len(judged), n=len(judged))
        judge_tokens = [j.usage.total_tokens for j in judged if j.usage is not None]
        if judge_tokens:
            agg["judge_tokens_total"] = AggregateScore(
                value=float(sum(judge_tokens)), n=len(judge_tokens)
            )

    fresh_latency = [r.latency_ms for r in ok if not r.cached and r.latency_ms is not None]
    if fresh_latency:
        n = len(fresh_latency)
        agg["latency_ms_p50"] = AggregateScore(value=percentile(fresh_latency, 50), n=n)
        agg["latency_ms_p95"] = AggregateScore(value=percentile(fresh_latency, 95), n=n)

    usages = [r.usage for r in ok if r.usage is not None]
    if usages:
        agg["tokens_prompt_mean"] = _mean([float(u.prompt_tokens) for u in usages])
        agg["tokens_completion_mean"] = _mean([float(u.completion_tokens) for u in usages])
        agg["tokens_total"] = AggregateScore(
            value=float(sum(u.total_tokens for u in usages)), n=len(usages)
        )
    return agg
