"""Self-contained HTML report (one file, inline CSS and SVG, no JavaScript, no network).

Security: emails, reference summaries and model outputs are untrusted text. Jinja2's
autoescaping is on for every template, so ``<script>`` in an email is shown, never run.
Only the sparkline SVG (built from numbers alone) is marked safe.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from regguard import __version__
from regguard.core.types import (
    CaseChange,
    CaseResult,
    Comparison,
    MetricDelta,
    MetricKind,
    RunResult,
    Severity,
    ThresholdLevel,
)
from regguard.reporting.svg import sparkline

_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class CaseView:
    """One case as shown in the report (first sample when there are several)."""

    case_id: str
    label: str | None
    critical: bool
    change: str | None  # CaseChange value, None without a comparison
    passed: bool | None  # None: infrastructure error
    input_text: str | None
    expected: str | None
    baseline_output: str | None
    candidate_output: str | None
    failed_metrics: tuple[str, ...]
    judge: str | None  # "4/5: reason" or None
    baseline_judge: str | None
    error: str | None


@dataclass(frozen=True)
class ReportData:
    run: RunResult
    comparison: Comparison | None = None
    baseline: RunResult | None = None
    inputs: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    expected: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    trends: Mapping[str, Sequence[float]] = field(default_factory=dict)
    notes: Sequence[str] = ()


def _first_samples(run: RunResult | None) -> dict[str, CaseResult]:
    first: dict[str, CaseResult] = {}
    for c in run.cases if run else []:
        if c.case_id not in first or c.sample_idx < first[c.case_id].sample_idx:
            first[c.case_id] = c
    return first


def _output(c: CaseResult | None) -> str | None:
    if c is None:
        return None
    if c.error is not None:
        return f"[error] {c.error.type}: {c.error.message}"
    if c.parsed_output is not None:
        return json.dumps(c.parsed_output, ensure_ascii=False, indent=1)
    return c.raw_output


def _judge(c: CaseResult | None) -> str | None:
    if c is None or c.judge is None:
        return None
    if c.judge.score is None:
        return f"judge error: {c.judge.error.type if c.judge.error else 'unknown'}"
    return f"{c.judge.score}/5: {c.judge.reason}"


def _text(values: Mapping[str, Any] | None) -> str | None:
    if not values:
        return None
    if len(values) == 1:
        return str(next(iter(values.values())))
    return "\n".join(f"{k}: {v}" for k, v in values.items())


def case_views(data: ReportData) -> list[CaseView]:
    candidate = _first_samples(data.run)
    baseline = _first_samples(data.baseline)
    diffs = {d.case_id: d for d in data.comparison.cases} if data.comparison else {}
    labels = data.run.meta.case_labels
    critical = set(data.run.meta.critical_case_ids)
    order = sorted(candidate.keys() | baseline.keys())
    views = []
    for case_id in order:
        c, b, d = candidate.get(case_id), baseline.get(case_id), diffs.get(case_id)
        expected = data.expected.get(case_id)
        views.append(
            CaseView(
                case_id=case_id,
                label=(d.label if d else None) or labels.get(case_id),
                critical=(d.critical if d else False) or case_id in critical,
                change=d.change.value if d else None,
                passed=None if c is None or c.error is not None else c.passed,
                input_text=_text(data.inputs.get(case_id)),
                expected=json.dumps(dict(expected), ensure_ascii=False, indent=1)
                if expected
                else None,
                baseline_output=_output(b),
                candidate_output=_output(c),
                failed_metrics=tuple(
                    sorted(s.name for s in c.scores if s.passed is False) if c else ()
                ),
                judge=_judge(c),
                baseline_judge=_judge(b),
                error=c.error.message if c and c.error else None,
            )
        )
    return views


def _fmt_value(m: MetricDelta, value: float) -> str:
    if m.kind is MetricKind.RATE:
        return f"{value:.1%}"
    return f"{value:.2f}" if abs(value) < 10 else f"{value:.0f}"


def _fmt_delta(m: MetricDelta) -> str:
    if m.delta is None:
        return "n/a"
    return f"{m.delta * 100:+.1f} pts" if m.unit == "absolute" else f"{m.delta * 100:+.0f}%"


def _aggregate_rows(run: RunResult) -> list[tuple[str, str, int]]:
    rows = []
    for name, agg in sorted(run.aggregates.items()):
        is_count = name.startswith(("latency", "tokens", "judge_tokens"))
        is_scale = name in ("summary_judge", "summary_similarity", "macro_f1")
        value = (
            f"{agg.value:.0f}"
            if is_count
            else f"{agg.value:.2f}"
            if is_scale
            else f"{agg.value:.1%}"
        )
        rows.append((name, value, agg.n))
    return rows


def render_html(data: ReportData, *, now: datetime | None = None) -> str:
    comparison = data.comparison
    views = case_views(data)
    changed = [
        v for v in views if v.change in (CaseChange.REGRESSED.value, CaseChange.IMPROVED.value)
    ]
    problems = [v for v in views if v not in changed and (v.passed is False or v.passed is None)]
    verdict = comparison.verdict.value if comparison else data.run.status.value
    template = _ENV.get_template("report.html.j2")
    return template.render(
        run=data.run,
        meta=data.run.meta,
        comparison=comparison,
        baseline=data.baseline,
        verdict=verdict,
        verdict_class=verdict if comparison else ("pass" if verdict == "completed" else "error"),
        reasons=[r for r in comparison.reasons if r.severity is not Severity.INFO]
        if comparison
        else [],
        info=[r for r in comparison.reasons if r.severity is Severity.INFO] if comparison else [],
        metrics=[
            {
                "name": m.metric,
                "baseline": _fmt_value(m, m.baseline),
                "candidate": _fmt_value(m, m.candidate),
                "delta": _fmt_delta(m),
                "flips": f"{m.regressed}/{m.improved}" if m.regressed is not None else "\u2013",
                "p": f"{m.p_value:.3f}" if m.p_value is not None else "\u2013",
                "level": "" if m.level is ThresholdLevel.OK else m.level.value,
                "gating": m.gating,
                "trend": Markup(sparkline(data.trends.get(m.metric, ()))),  # noqa: S704 - numbers only
            }
            for m in (comparison.metrics if comparison else [])
        ],
        aggregates=_aggregate_rows(data.run),
        trends={
            name: Markup(sparkline(values))  # noqa: S704 - built from numbers only
            for name, values in data.trends.items()
            if len(values) >= 2
        },
        counts=comparison.counts if comparison else {},
        changed=changed,
        problems=problems,
        views=views,
        notes=list(data.notes),
        generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC"),
        version=__version__,
    )
