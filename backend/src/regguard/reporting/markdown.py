"""Short Markdown summary of a run and its comparison, for a GitHub PR comment.

Deliberately contains no email text and no raw model output: PR comments are widely
visible, and real inputs may contain personal data. Details live in the HTML report.
"""

from regguard import __version__
from regguard.core.types import (
    CaseChange,
    Comparison,
    MetricDelta,
    MetricKind,
    RunResult,
    RunStatus,
    Severity,
    ThresholdLevel,
    Verdict,
)

MAX_CASES = 10
_ICONS = {
    Verdict.PASS: "✅",
    Verdict.WARN: "⚠️",
    Verdict.FAIL: "❌",
    Verdict.ERROR: "🛑",
}


def md(text: object) -> str:
    """Escape a value for a Markdown table cell or inline text."""
    return (
        str(text)
        .replace("->", "→")
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "'")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _value(m: MetricDelta, value: float) -> str:
    if m.kind is MetricKind.RATE:
        return f"{value:.1%}"
    return f"{value:.2f}" if abs(value) < 10 else f"{value:.0f}"


def _delta(m: MetricDelta) -> str:
    if m.delta is None:
        return "n/a"
    return f"{m.delta * 100:+.1f} pts" if m.unit == "absolute" else f"{m.delta * 100:+.0f}%"


def _metric_rows(comparison: Comparison) -> list[str]:
    rows = [
        "| Metric | Baseline | Candidate | Change | \u2212/+ | p | Level |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for m in comparison.metrics:
        flips = f"{m.regressed}/{m.improved}" if m.regressed is not None else "\u2013"
        p_value = f"{m.p_value:.3f}" if m.p_value is not None else "\u2013"
        level = "" if m.level is ThresholdLevel.OK else f"**{m.level.value.upper()}**"
        if level and not m.gating:
            level += " (info)"
        rows.append(
            f"| `{md(m.metric)}` | {_value(m, m.baseline)} | {_value(m, m.candidate)} "
            f"| {_delta(m)} | {flips} | {p_value} | {level} |"
        )
    return rows


def _headline(run: RunResult, comparison: Comparison | None) -> str:
    if comparison is None:
        icon = "✅" if run.status is RunStatus.COMPLETED else "🛑"
        return f"## {icon} RegressionGuard: run {run.status.value.upper()}"
    return f"## {_ICONS[comparison.verdict]} RegressionGuard: {comparison.verdict.value.upper()}"


def render_markdown(
    run: RunResult,
    comparison: Comparison | None = None,
    *,
    baseline: RunResult | None = None,
    report_url: str | None = None,
) -> str:
    m = run.meta
    lines = [_headline(run, comparison), ""]
    against = ""
    if comparison is not None:
        name = comparison.baseline_name or comparison.baseline_run_id
        base_prompt = f" ({md(baseline.meta.prompt_version)})" if baseline else ""
        against = f" vs baseline `{md(name)}`{base_prompt}"
    lines.append(
        f"**App** `{md(m.app)}` · **prompt** `{md(m.prompt_version)}` "
        f"(`{m.prompt_hash[7:19]}`){against} · **model** `{md(m.model)}` · "
        f"**dataset** `{md(m.dataset_version)}` · **cases** {len({c.case_id for c in run.cases})}"
    )
    if run.error:
        lines += ["", f"> **Run error:** {md(run.error)}"]

    if comparison is not None:
        decisive = [r for r in comparison.reasons if r.severity is not Severity.INFO]
        lines += ["", "### Why"]
        if decisive:
            lines += [
                f"- **{r.severity.value.upper()}** `{r.code}`: {md(r.message)}" for r in decisive
            ]
        else:
            lines.append("- No metric crossed a threshold.")
        if comparison.metrics:
            lines += ["", "### Metrics", *_metric_rows(comparison)]

        changed = [
            d for d in comparison.cases if d.change in (CaseChange.REGRESSED, CaseChange.IMPROVED)
        ]
        regressed = [d for d in changed if d.change is CaseChange.REGRESSED]
        if changed:
            lines += [
                "",
                f"### Changed cases ({len(regressed)} regressed, "
                f"{len(changed) - len(regressed)} improved)",
                "| Case | Category | Change | Now failing |",
                "|---|---|---|---|",
            ]
            for d in changed[:MAX_CASES]:
                flag = " 🔒 critical" if d.critical else ""
                failing = ", ".join(d.candidate_failed_metrics) or "\u2013"
                lines.append(
                    f"| `{md(d.case_id)}`{flag} | {md(d.label or '\u2013')} "
                    f"| {d.change.value} | {md(failing)} |"
                )
            if len(changed) > MAX_CASES:
                lines.append(f"\n…and {len(changed) - MAX_CASES} more in the full report.")
        notes = [r for r in comparison.reasons if r.severity is Severity.INFO]
        if notes:
            lines += ["", "<details><summary>Notes</summary>", ""]
            lines += [f"- `{r.code}`: {md(r.message)}" for r in notes]
            lines += ["", "</details>"]

    if report_url:
        lines += ["", f"📄 [Full report]({report_url})"]
    lines += ["", f"<sub>RegressionGuard {__version__} · run `{md(m.run_id)}`</sub>", ""]
    return "\n".join(lines)
