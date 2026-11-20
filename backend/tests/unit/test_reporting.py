"""HTML report and Markdown summary (pure rendering)."""

import os
from datetime import UTC, datetime
from pathlib import Path

from regguard.comparison.verdict import compare
from regguard.core.gating import GateConfig
from regguard.core.types import CaseResult, MetricScore, RunStatus
from regguard.reporting.html import ReportData, case_views, render_html
from regguard.reporting.markdown import MAX_CASES, md, render_markdown
from regguard.reporting.svg import sparkline
from tests.unit.run_factory import make_run, outcomes

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

BASE = make_run(outcomes(30), run_id="base", critical=["email-0001"])
CAND = make_run(
    outcomes(30, fail=[1, 2, 3]), run_id="cand", prompt_version="v2", critical=["email-0001"]
)
COMPARISON = compare(BASE, CAND, GateConfig(), baseline_name="main", now=NOW)


def _golden(name: str, actual: str) -> None:
    """Compare with tests/golden/<name>; REGGUARD_UPDATE_GOLDEN=1 rewrites it."""
    path = GOLDEN / name
    if os.environ.get("REGGUARD_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == actual


# --- Markdown -------------------------------------------------------------------------------


def test_markdown_fail_summary_matches_golden_file() -> None:
    _golden("summary_fail.md", render_markdown(CAND, COMPARISON, baseline=BASE))


def test_markdown_escapes_table_breaking_characters() -> None:
    assert md("a|b") == "a\\|b"
    assert md("line\nbreak") == "line break"
    assert md("`code`") == "'code'"
    assert md("<b>") == "&lt;b&gt;"
    assert md("1 -> 2") == "1 → 2"


def test_markdown_without_comparison_and_with_run_error() -> None:
    ok = render_markdown(make_run(outcomes(4)))
    assert ok.startswith("## ✅ RegressionGuard: run COMPLETED")
    assert "### Why" not in ok
    failed = render_markdown(make_run(outcomes(4), status=RunStatus.ERROR))
    assert "\U0001f6d1" in failed  # stop sign
    assert "**Run error:** aborted" in failed


def test_markdown_lists_at_most_max_cases_and_links_the_report() -> None:
    many = make_run(outcomes(40, fail=range(1, 21)), run_id="many")
    comparison = compare(make_run(outcomes(40)), many, GateConfig(), now=NOW)
    text = render_markdown(many, comparison, report_url="https://example.test/r.html")
    assert text.count("| regressed |") == MAX_CASES
    assert "and 10 more in the full report" in text
    assert "[Full report](https://example.test/r.html)" in text


def test_markdown_never_contains_inputs_or_raw_outputs() -> None:
    secret = make_run({"email-0001": "pass"}, run_id="c")
    case = secret.cases[0].model_copy(update={"raw_output": "SECRET-OUTPUT"})
    text = render_markdown(secret.model_copy(update={"cases": [case]}))
    assert "SECRET-OUTPUT" not in text


# --- HTML ----------------------------------------------------------------------------------

XSS = "<script>alert('x')</script>"


def _xss_data() -> ReportData:
    case = CaseResult(
        case_id="email-0001",
        raw_output="{}",
        parsed_output={"category": "billing", "summary": f"<img src=x onerror=alert(1)> {XSS}"},
        scores=[MetricScore(name="schema_valid", value=1.0, passed=True)],
        passed=True,
    )
    run = CAND.model_copy(update={"cases": [case, *CAND.cases[1:]]})
    return ReportData(
        run=run,
        comparison=COMPARISON,
        baseline=BASE,
        inputs={"email-0001": {"email": f"Hello {XSS}"}},
        expected={"email-0001": {"category": "billing", "summary": "Customer & co."}},
        trends={"schema_valid": [1.0, 0.9, 1.0]},
        notes=["a <b>note</b>"],
    )


def test_html_escapes_untrusted_text() -> None:
    html = render_html(_xss_data(), now=NOW)
    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "a &lt;b&gt;note&lt;/b&gt;" in html


def test_html_comparison_report_sections() -> None:
    html = render_html(_xss_data(), now=NOW)
    assert '<span class="badge fail">fail</span>' in html
    assert "Why this verdict" in html
    assert "critical_regression" in html
    assert "Changed cases" in html
    assert "critical case" in html  # email-0001 is critical and regressed
    assert "Hello &lt;script&gt;" in html  # the input is shown (escaped)
    assert 'class="spark"' in html  # trend sparkline for schema_valid
    assert "generated 2026-11-20 12:00 UTC" in html


def test_html_single_run_without_comparison() -> None:
    html = render_html(ReportData(run=make_run(outcomes(4))), now=NOW)
    assert "Single run, no baseline comparison." in html
    assert "<h2>Scores</h2>" in html
    assert "Why this verdict" not in html


def test_case_views_pair_baseline_and_candidate_outputs() -> None:
    views = {v.case_id: v for v in case_views(_xss_data())}
    regressed = views["email-0002"]
    assert regressed.change == "regressed"
    assert regressed.passed is False
    assert regressed.failed_metrics == ("label_exact",)
    assert regressed.baseline_output is not None
    assert views["email-0001"].critical is True


def test_sparkline() -> None:
    assert sparkline([]) == ""
    assert sparkline([0.5]) == ""
    svg = sparkline([0.1, 0.5, 0.3])
    assert svg.startswith('<svg class="spark"')
    assert "polyline" in svg
    assert sparkline([1.0, 1.0]).count("circle") == 1  # flat series: no division by zero
