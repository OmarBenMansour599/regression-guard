"""Case diff, metric deltas, gate configuration and the PASS / WARN / FAIL verdict."""

import pytest
from pydantic import ValidationError

from regguard.comparison.diff import case_labels, case_outcomes
from regguard.comparison.verdict import compare
from regguard.core.errors import ComparisonError
from regguard.core.gating import GateConfig, MetricThreshold
from regguard.core.types import (
    AggregateScore,
    CaseResult,
    Comparison,
    MetricDelta,
    MetricKind,
    MetricScore,
    RunResult,
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


def test_broken_format_is_not_a_classification_regression() -> None:
    """The Phase 5a demo: v2 wrapped 4 outputs in a list. Format failed, labels did not."""
    base = make_run(outcomes(12))
    cand = make_run(outcomes(12, fail=[1, 2, 3, 4], code="schema"), run_id="cand")
    c = compare(base, cand, GATE)
    assert c.verdict is Verdict.FAIL
    schema = metric(c, "schema_valid")
    assert (schema.regressed, schema.level) == (4, ThresholdLevel.CRITICAL)
    label = metric(c, "label_exact")
    assert label.n == 8  # the 4 invalid cases are not paired for the label
    assert label.delta == 0
    assert label.level is ThresholdLevel.OK
    assert {r.metric for r in c.reasons if r.severity is Severity.FAIL} == {"schema_valid"}


def test_continuous_values_pair_with_epsilon_and_sign_test() -> None:
    ids = [f"email-{i:04d}" for i in range(1, 13)]
    base = make_run(outcomes(12), similarity=dict.fromkeys(ids, 0.8))
    worse = {i: 0.8 for i in ids}
    worse.update({ids[0]: 0.3, ids[1]: 0.3, ids[2]: 0.3, ids[3]: 0.3, ids[4]: 0.75})  # 4 real drops
    c = compare(base, make_run(outcomes(12), similarity=worse, run_id="cand"), GATE)
    sim = metric(c, "summary_similarity")
    assert sim.kind is MetricKind.VALUE
    assert sim.n == 12
    assert (sim.regressed, sim.improved) == (4, 0)  # 0.05 drop is within epsilon 0.10
    assert sim.p_value == pytest.approx(0.0625)
    assert sim.level is ThresholdLevel.WARN
    assert c.verdict is Verdict.PASS  # similarity is informational
    assert "threshold_crossed_info" in codes(c)


def judged(run: RunResult, score: float, judge: dict[str, str] | None) -> RunResult:
    """Give every valid case a summary_judge score and record which judge produced it."""
    cases = [
        c.model_copy(
            update={
                "scores": [*c.scores, MetricScore(name="summary_judge", value=score, passed=None)]
            }
        )
        if c.parsed_output is not None
        else c
        for c in run.cases
    ]
    meta = run.meta.model_copy(update={"judge": judge})
    return run.model_copy(update={"cases": cases, "meta": meta})


JUDGE_V1 = {"model": "judge-model", "prompt_version": "v1", "prompt_hash": "sha256:1"}
JUDGE_V2 = {**JUDGE_V1, "prompt_version": "v2", "prompt_hash": "sha256:2"}


def test_judge_scores_compared_when_the_judge_is_the_same() -> None:
    base = judged(make_run(outcomes(12)), 5.0, JUDGE_V1)
    cand = judged(make_run(outcomes(12), run_id="cand"), 3.0, JUDGE_V1)
    c = compare(base, cand, GATE)
    judge = metric(c, "summary_judge")
    assert judge.kind is MetricKind.VALUE
    assert (judge.regressed, judge.improved) == (12, 0)
    assert judge.level is ThresholdLevel.CRITICAL
    assert "judge_changed" not in codes(c)
    assert c.verdict is Verdict.PASS  # judge is report-only by default


@pytest.mark.parametrize(
    "other",
    [
        JUDGE_V2,  # judge prompt changed
        {**JUDGE_V1, "model": "another-judge"},  # judge model changed
        None,  # an older run without judge provenance
    ],
)
def test_judge_scores_not_compared_across_different_judges(other: dict[str, str] | None) -> None:
    base = judged(make_run(outcomes(12)), 5.0, JUDGE_V1)
    cand = judged(make_run(outcomes(12), run_id="cand"), 3.0, other)
    c = compare(base, cand, GATE)
    assert "summary_judge" not in {m.metric for m in c.metrics}
    reason = next(r for r in c.reasons if r.code == "judge_changed")
    assert reason.severity is Severity.INFO
    assert reason.metric == "summary_judge"
    assert c.verdict is Verdict.PASS


def test_judge_change_warns_once_the_judge_is_gating() -> None:
    gate = GateConfig(
        metrics={"summary_judge": MetricThreshold(warn=-0.05, unit="relative", gating=True)}
    )
    base = judged(make_run(outcomes(12)), 5.0, JUDGE_V1)
    cand = judged(make_run(outcomes(12), run_id="cand"), 5.0, JUDGE_V2)
    c = compare(base, cand, gate)
    assert next(r for r in c.reasons if r.code == "judge_changed").severity is Severity.WARN
    assert c.verdict is Verdict.WARN


def test_macro_f1_is_compared_as_an_aggregate() -> None:
    base = make_run(outcomes(12))
    cand = make_run(outcomes(12), run_id="cand")
    agg = {**cand.aggregates, "macro_f1": AggregateScore(value=0.70, n=12)}
    base_agg = {**base.aggregates, "macro_f1": AggregateScore(value=0.90, n=12)}
    c = compare(
        base.model_copy(update={"aggregates": base_agg}),
        cand.model_copy(update={"aggregates": agg}),
        GATE,
    )
    f1 = metric(c, "macro_f1")
    assert f1.kind is MetricKind.AGGREGATE
    assert f1.delta == pytest.approx(-0.20)
    assert f1.level is ThresholdLevel.CRITICAL
    assert c.verdict is Verdict.PASS  # informational by default


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
