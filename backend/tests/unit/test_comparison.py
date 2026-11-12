"""Case diff, metric deltas, gate configuration and the PASS / WARN / FAIL verdict."""

import pytest
from pydantic import ValidationError

from regguard.comparison.diff import case_labels, case_outcomes
from regguard.comparison.verdict import compare
from regguard.core.errors import ComparisonError
from regguard.core.gating import GateConfig, MetricThreshold
from regguard.core.types import (
    CaseResult,
    Comparison,
    MetricDelta,
    MetricScore,
    RunStatus,
    Severity,
    ThresholdLevel,
    Verdict,
)
from tests.unit.run_factory import make_case, make_run, outcomes

GATE = GateConfig()


def codes(c: Comparison) -> set[str]:
    return {r.code for r in c.reasons}


def metric(c: Comparison, name: str) -> MetricDelta:
    return next(m for m in c.metrics if m.metric == name)


# --- case outcomes and diff ---------------------------------------------------------------


def test_majority_vote_over_samples() -> None:
    run = make_run({})
    samples = [
        make_case("a", "pass", sample_idx=0),
        make_case("a", "label", sample_idx=1),
        make_case("a", "pass", sample_idx=2),
        make_case("b", "pass", sample_idx=0),
        make_case("b", "label", sample_idx=1),  # tie -> fail
    ]
    result = case_outcomes(run.model_copy(update={"cases": samples}))
    assert result["a"].passed is True
    assert result["b"].passed is False
    assert result["b"].metrics == {"schema_valid": True, "label_exact": False}


def test_any_errored_sample_skips_the_case() -> None:
    run = make_run({})
    samples = [make_case("a", "pass"), make_case("a", "error", sample_idx=1)]
    assert case_outcomes(run.model_copy(update={"cases": samples}))["a"].passed is None


def test_case_labels_fall_back_to_score_detail_for_old_runs() -> None:
    run = make_run({}, labels={})
    case = CaseResult(
        case_id="x",
        passed=True,
        scores=[
            MetricScore(name="label_exact", value=1.0, passed=True, detail={"expected": "billing"})
        ],
    )
    assert case_labels(run.model_copy(update={"cases": [case]})) == {"x": "billing"}


# --- verdicts ---------------------------------------------------------------------------


def test_identical_runs_pass_with_no_flips() -> None:
    run = make_run(outcomes(12))
    c = compare(run, run, GATE)
    assert c.verdict is Verdict.PASS
    assert c.counts == {"still_pass": 12}
    assert all(r.severity is Severity.INFO for r in c.reasons)
    assert metric(c, "label_exact").regressed == 0
    assert metric(c, "label_exact").p_value == 1.0


def test_significant_ten_percent_regression_fails() -> None:
    base = make_run(outcomes(40))
    cand = make_run(outcomes(40, fail=[1, 2, 3, 4]), run_id="cand")
    c = compare(base, cand, GATE)
    assert c.verdict is Verdict.FAIL
    m = metric(c, "label_exact")
    assert m.delta == pytest.approx(-0.10)
    assert (m.regressed, m.improved) == (4, 0)
    assert m.p_value == pytest.approx(0.0625)
    assert m.level is ThresholdLevel.CRITICAL
    assert "critical_regression" in codes(c)
    assert c.counts["regressed"] == 4


def test_min_regressed_cases_is_evidence_even_without_significance() -> None:
    base = make_run(outcomes(30))
    cand = make_run(outcomes(30, fail=[1, 2, 3]), run_id="cand")  # -10 pts, p = 0.125
    c = compare(base, cand, GATE)
    assert c.verdict is Verdict.FAIL
    assert "critical_regression" in codes(c)


def test_one_flip_on_small_dataset_is_underpowered_warn_not_fail() -> None:
    base = make_run(outcomes(12))
    cand = make_run(outcomes(12, fail=[1]), run_id="cand")  # -8.3 pts crosses critical
    c = compare(base, cand, GATE)
    assert c.verdict is Verdict.WARN
    assert "critical_underpowered" in codes(c)
    assert "critical_regression" not in codes(c)


def test_small_drop_on_large_dataset_is_warn() -> None:
    base = make_run(outcomes(40))
    cand = make_run(outcomes(40, fail=[2, 3]), run_id="cand")  # -5 pts: warn, not critical
    c = compare(base, cand, GATE)
    assert metric(c, "label_exact").level is ThresholdLevel.WARN
    assert c.verdict is Verdict.WARN


def test_improvements_pass() -> None:
    base = make_run(outcomes(12, fail=[1, 2]))
    cand = make_run(outcomes(12), run_id="cand")
    c = compare(base, cand, GATE)
    assert c.verdict is Verdict.PASS
    assert c.counts["improved"] == 2
    assert metric(c, "label_exact").delta == pytest.approx(2 / 12)


def test_per_category_slices_are_compared() -> None:
    base = make_run(outcomes(40))
    cand = make_run(outcomes(40, fail=[1]), run_id="cand")  # email-0001 is "billing"
    c = compare(base, cand, GATE)
    billing = metric(c, "label_exact/billing")
    assert billing.n == 10
    assert billing.delta == pytest.approx(-0.10)
    assert billing.level is ThresholdLevel.WARN
    assert metric(c, "label_exact/technical").delta == 0


def test_regressed_critical_case_fails_even_within_thresholds() -> None:
    base = make_run(outcomes(40), critical=["email-0001"])
    cand = make_run(outcomes(40, fail=[1]), run_id="cand", critical=["email-0001"])
    c = compare(base, cand, GATE)
    assert metric(c, "label_exact").level is ThresholdLevel.OK  # -2.5 pts
    assert c.verdict is Verdict.FAIL
    assert "critical_case_regressed" in codes(c)
    assert next(d for d in c.cases if d.case_id == "email-0001").critical


def test_critical_case_rule_can_be_disabled() -> None:
    base = make_run(outcomes(40), critical=["email-0005"])
    cand = make_run(outcomes(40, fail=[5]), run_id="cand")
    gate = GateConfig(critical_cases_must_not_regress=False)
    assert "critical_case_regressed" not in codes(compare(base, cand, gate))


def test_schema_floor_is_a_hard_rule() -> None:
    run = make_run(outcomes(12, fail=[1], code="schema"))  # 91.7% < 95%, same as baseline
    c = compare(
        run, run.model_copy(update={"meta": run.meta.model_copy(update={"run_id": "x"})}), GATE
    )
    assert c.verdict is Verdict.FAIL
    assert "schema_valid_floor" in codes(c)


def test_token_blowup_fails_and_moderate_growth_warns() -> None:
    base = make_run(outcomes(12), tokens=100)
    assert compare(base, make_run(outcomes(12), tokens=160), GATE).verdict is Verdict.FAIL
    c = compare(base, make_run(outcomes(12), tokens=125), GATE)
    assert c.verdict is Verdict.WARN
    assert metric(c, "tokens_per_case").delta == pytest.approx(0.25)


def test_latency_is_reported_but_not_gating_by_default() -> None:
    base = make_run(outcomes(12), latency_p95=1000.0)
    c = compare(base, make_run(outcomes(12), latency_p95=3000.0), GATE)
    assert c.verdict is Verdict.PASS
    assert metric(c, "latency_ms_p95").level is ThresholdLevel.WARN
    assert "threshold_crossed_info" in codes(c)


# --- comparability and infrastructure errors -------------------------------------------------


def test_errored_candidate_gives_error_verdict_not_fail() -> None:
    base = make_run(outcomes(12))
    cand = make_run(outcomes(12, fail=[1, 2, 3, 4, 5], code="error"), status=RunStatus.ERROR)
    c = compare(base, cand, GATE)
    assert c.verdict is Verdict.ERROR
    assert codes(c) == {"candidate_error"}


def test_errored_cases_are_skipped_not_regressed() -> None:
    base = make_run(outcomes(12))
    cand = make_run(outcomes(12, fail=[1], code="error"), run_id="cand")
    c = compare(base, cand, GATE)
    assert c.counts == {"still_pass": 11, "skipped": 1}
    assert c.verdict is Verdict.PASS
    assert "cases_not_compared" in codes(c)


def test_baseline_with_error_status_is_refused() -> None:
    base = make_run(outcomes(12), status=RunStatus.ERROR)
    with pytest.raises(ComparisonError, match="status error"):
        compare(base, make_run(outcomes(12)), GATE)


def test_different_apps_are_refused() -> None:
    with pytest.raises(ComparisonError, match="different apps"):
        compare(make_run(outcomes(3)), make_run(outcomes(3), app="other"), GATE)


def test_dataset_change_refused_unless_allowed() -> None:
    base = make_run(outcomes(12))
    cand = make_run(outcomes(14), dataset_hash="sha256:" + "c" * 64)
    with pytest.raises(ComparisonError, match="--allow-dataset-change"):
        compare(base, cand, GATE)
    c = compare(base, cand, GATE, allow_dataset_change=True)
    assert c.verdict is Verdict.WARN
    assert "dataset_changed" in codes(c)
    assert c.counts["new"] == 2
    assert metric(c, "label_exact").n == 12


def test_removed_cases_are_reported() -> None:
    base = make_run(outcomes(14))
    c = compare(base, make_run(outcomes(12)), GATE)
    assert c.counts["removed"] == 2


def test_no_common_cases_is_an_error() -> None:
    base = make_run({"a": "pass"})
    cand = make_run({"b": "pass"})
    with pytest.raises(ComparisonError, match="no successfully evaluated cases"):
        compare(base, cand, GATE)


def test_comparison_records_gate_and_round_trips() -> None:
    run = make_run(outcomes(4))
    c = compare(run, run, GATE, baseline_name="main")
    assert c.gate["alpha"] == 0.10
    assert Comparison.model_validate_json(c.model_dump_json()) == c


def test_custom_gate_thresholds_change_the_verdict() -> None:
    base = make_run(outcomes(40))
    cand = make_run(outcomes(40, fail=[2, 3]), run_id="cand")  # -5 pts
    lenient = GateConfig(
        metrics={
            "label_exact": MetricThreshold(warn=-0.10),
            "label_exact/*": MetricThreshold(warn=-0.50),
        }
    )
    assert compare(base, cand, lenient).verdict is Verdict.PASS


# --- gate configuration -------------------------------------------------------------------


def test_user_thresholds_merge_with_defaults() -> None:
    gate = GateConfig(metrics={"label_exact": MetricThreshold(warn=-0.05, critical=-0.10)})
    assert gate.threshold_for("label_exact") == MetricThreshold(warn=-0.05, critical=-0.10)
    assert gate.threshold_for("schema_valid") is not None  # default kept


def test_threshold_glob_patterns() -> None:
    assert GATE.threshold_for("label_exact/billing") == GATE.metrics["label_exact/*"]
    assert GATE.threshold_for("pass_rate") is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"warn": 0.0},
        {"warn": -0.03, "critical": 0.08},
        {"warn": -0.08, "critical": -0.03},
    ],
)
def test_invalid_thresholds_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        MetricThreshold(**kwargs)  # type: ignore[arg-type]
