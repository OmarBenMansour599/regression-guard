"""Phase 9 CI gate: planning from changed files, verdict aggregation, PR comment, CLI."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from regguard.apps.config import AppConfig, JudgeConfig
from regguard.cli.main import EXIT_CONFIG_ERROR, EXIT_GATE_FAILED, EXIT_PROVIDER_ERROR, app
from regguard.comparison.verdict import compare
from regguard.core.gating import GateConfig
from regguard.core.types import BaselineFile, BaselineHeader, RunResult, RunStatus, Verdict
from regguard.services.ci_service import (
    COMMENT_MARKER,
    MAX_PROMPTS,
    CiPlan,
    PromptOutcome,
    collect_outcomes,
    find_repo_root,
    gate_verdict,
    plan_ci,
    render_pr_comment,
)
from regguard.services.compare_service import save_comparison
from regguard.storage.baseline_store import save_baseline
from regguard.storage.file_store import save_run
from tests.unit.run_factory import make_run, outcomes
from tests.unit.test_cli_run import config  # noqa: F401 - pytest fixture

runner = CliRunner()


def _baseline(baselines_dir: Path, prompt_version: str = "v1", name: str = "main") -> None:
    run = make_run(outcomes(12), run_id="base", prompt_version=prompt_version)
    header = BaselineHeader(
        name=name,
        app="t",
        source_run_id="base",
        promoted_at=datetime(2026, 11, 20, tzinfo=UTC),
        regguard_version="0.0.0",
    )
    save_baseline(baselines_dir, BaselineFile(header=header, run=run))


@pytest.fixture
def repo(tmp_path: Path) -> tuple[AppConfig, Path, Path]:
    """A repo with app/{regguard.yaml, prompts/classify, prompts/judge, datasets, baselines}."""
    (tmp_path / ".git").mkdir()
    app_dir = tmp_path / "app"
    for sub in ("prompts/classify", "prompts/judge", "datasets/emails/v1", "baselines"):
        (app_dir / sub).mkdir(parents=True)
    for version in ("v1", "v2", "v3", "v4", "v5"):
        (app_dir / "prompts" / "classify" / f"{version}.yaml").write_text("x", encoding="utf-8")
    config_path = app_dir / "regguard.yaml"
    config_path.write_text("x", encoding="utf-8")
    cfg = AppConfig(
        name="t",
        app="support_email_classifier",
        prompts_dir=(app_dir / "prompts" / "classify").resolve(),
        datasets_dir=(app_dir / "datasets").resolve(),
        baselines_dir=(app_dir / "baselines").resolve(),
        judge=JudgeConfig(prompts_dir=(app_dir / "prompts" / "judge").resolve()),
    )
    _baseline(cfg.baselines_dir)
    return cfg, config_path, tmp_path


def _plan(repo: tuple[AppConfig, Path, Path], *changed: str) -> CiPlan:
    cfg, config_path, root = repo
    return plan_ci(cfg, config_path, changed, repo_root=root)


# --- planning ----------------------------------------------------------------------------


def test_unrelated_changes_need_nothing(repo: tuple[AppConfig, Path, Path]) -> None:
    plan = _plan(repo, "README.md", "backend/src/regguard/cli/main.py", "")
    assert not plan.evaluate and not plan.relevant and plan.blocking is None


def test_changed_prompt_is_evaluated(repo: tuple[AppConfig, Path, Path]) -> None:
    plan = _plan(repo, "app/prompts/classify/v2.yaml", "docs/x.md")
    assert plan.prompt_versions == ("v2",)
    assert plan.evaluate and plan.relevant


def test_deleted_prompt_is_noted_not_evaluated(repo: tuple[AppConfig, Path, Path]) -> None:
    plan = _plan(repo, "app/prompts/classify/v9.yaml")
    assert not plan.evaluate
    assert any("v9 was deleted" in n for n in plan.notes)


def test_config_change_reevaluates_the_baseline_prompt(repo: tuple[AppConfig, Path, Path]) -> None:
    plan = _plan(repo, "app/regguard.yaml")
    assert plan.config_changed
    assert plan.prompt_versions == ("v1",)  # the baseline's prompt version
    assert any("No prompt changed" in n for n in plan.notes)


def test_dataset_change_without_new_baseline_blocks(repo: tuple[AppConfig, Path, Path]) -> None:
    plan = _plan(repo, "app/datasets/emails/v1/cases.yaml", "app/prompts/classify/v2.yaml")
    assert plan.blocking is not None and "promote" in plan.blocking
    assert not plan.evaluate
    assert gate_verdict(plan, []) is Verdict.FAIL


def test_dataset_change_with_new_baseline_is_evaluated(repo: tuple[AppConfig, Path, Path]) -> None:
    plan = _plan(repo, "app/datasets/emails/v1/cases.yaml", "app/baselines/main.json")
    assert plan.blocking is None
    assert plan.prompt_versions == ("v1",)
    assert plan.baselines_changed == ("main",)
    assert any("reference moved" in n for n in plan.notes)


def test_judge_change_is_noted_but_not_run(repo: tuple[AppConfig, Path, Path]) -> None:
    plan = _plan(repo, "app/prompts/judge/v3.yaml")
    assert plan.judge_changed and plan.relevant and not plan.evaluate
    assert plan.prompt_versions == ()  # judge prompts are not classifier prompts


def test_too_many_prompts_block(repo: tuple[AppConfig, Path, Path]) -> None:
    changed = [f"app/prompts/classify/v{i}.yaml" for i in range(1, MAX_PROMPTS + 2)]
    plan = _plan(repo, *changed)
    assert plan.blocking is not None and "Split the PR" in plan.blocking


def test_missing_baseline_blocks(repo: tuple[AppConfig, Path, Path]) -> None:
    cfg, config_path, root = repo
    plan = plan_ci(cfg, config_path, ["app/prompts/classify/v2.yaml"], repo_root=root, baseline="x")
    assert plan.blocking is not None and "not found" in plan.blocking


def test_find_repo_root(repo: tuple[AppConfig, Path, Path]) -> None:
    _, config_path, root = repo
    assert find_repo_root(config_path.parent) == root.resolve()


# --- verdict and comment -----------------------------------------------------------------


def _outcome(candidate_fail: list[int], status: RunStatus = RunStatus.COMPLETED) -> PromptOutcome:
    base = make_run(outcomes(12), run_id="base")
    cand = make_run(outcomes(12, fail=candidate_fail), run_id="cand", status=status)
    comparison = compare(base, cand, GateConfig(), baseline_name="main")
    return PromptOutcome("v2", cand, comparison, base)


def test_gate_verdict_precedence() -> None:
    plan = CiPlan(prompt_versions=("v2", "v3"))
    passing, failing = _outcome([]), _outcome([1, 2, 3, 4])
    errored = PromptOutcome("v3", None, None, None)
    assert gate_verdict(plan, [passing, passing]) is Verdict.PASS
    assert gate_verdict(plan, [passing, errored]) is Verdict.ERROR
    assert gate_verdict(plan, [failing, errored]) is Verdict.FAIL
    assert gate_verdict(plan, [passing]) is Verdict.ERROR  # one planned run is missing
    assert gate_verdict(CiPlan(), []) is None


def test_comment_for_fail_has_marker_table_and_run_summary() -> None:
    plan = CiPlan(prompt_versions=("v2",), notes=("a note",))
    failing = _outcome([1, 2, 3, 4])
    text = render_pr_comment(plan, [failing], Verdict.FAIL, details_url="https://x/runs/1")
    assert text.startswith(COMMENT_MARKER)
    assert "## ❌ RegressionGuard gate: FAIL" in text
    assert "| `v2` | ❌ FAIL | `cand` |" in text
    assert "### ❌ RegressionGuard: FAIL" in text  # run summary nested one level down
    assert "[workflow run artifacts](https://x/runs/1)" in text
    assert "- a note" in text


def test_comment_for_error_explains_rerun() -> None:
    plan = CiPlan(prompt_versions=("v2",))
    errored = _outcome([1], status=RunStatus.ERROR)
    missing = PromptOutcome("v3", None, None, None)
    text = render_pr_comment(plan, [errored, missing], Verdict.ERROR)
    assert "Re-run the failed job" in text
    assert "no result (the run did not start" in text


def test_comment_nothing_to_evaluate_and_blocked() -> None:
    assert "nothing to evaluate" in render_pr_comment(CiPlan(), [], None)
    blocked = CiPlan(blocking="dataset | changed")
    text = render_pr_comment(blocked, [], Verdict.FAIL)
    assert "**Blocked:** dataset \\| changed" in text  # escaped for Markdown


def test_collect_outcomes_picks_newest_run_and_its_comparison(tmp_path: Path) -> None:
    cfg = AppConfig(
        name="t",
        app="support_email_classifier",
        prompts_dir=tmp_path,
        baselines_dir=tmp_path / "baselines",
    )
    _baseline(cfg.baselines_dir)
    runs = tmp_path / "runs"

    def dated(run_id: str, day: int, fail: list[int]) -> RunResult:
        run = make_run(outcomes(12, fail=fail), run_id=run_id, prompt_version="v2")
        started = datetime(2026, 11, day, tzinfo=UTC)
        return run.model_copy(update={"meta": run.meta.model_copy(update={"started_at": started})})

    old = dated("20261101T000000Z-old", 1, [])
    new = dated("20261102T000000Z-new", 2, [1])
    save_run(runs, old)
    save_run(runs, new)
    save_comparison(runs, compare(old, new, GateConfig(), baseline_name="main"))

    [found, missing] = collect_outcomes(cfg, runs, CiPlan(prompt_versions=("v2", "v3")))
    assert found.run is not None and found.run.meta.run_id == "20261102T000000Z-new"
    assert found.comparison is not None and found.reference is not None
    assert missing.run is None and missing.verdict is Verdict.ERROR


# --- CLI ---------------------------------------------------------------------------------


def _app_with_prompts(config_file: Path) -> None:
    """The CLI fixture points prompts_dir at the example app; ci plan needs a local copy."""
    from tests.conftest import EXAMPLE_APP

    shutil.copytree(EXAMPLE_APP / "prompts" / "classify", config_file.parent / "prompts")
    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    data["prompts_dir"] = "prompts"
    config_file.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_cli_plan_writes_json_and_github_output(config: str) -> None:  # noqa: F811
    config_file = Path(config)
    _app_with_prompts(config_file)
    _baseline(config_file.parent / "baselines")
    changed = config_file.parent / "changed.txt"
    # utf-8-sig adds a byte-order mark, as Windows PowerShell 5.1 does: it must be ignored
    changed.write_text("prompts/v2.yaml\nREADME.md\n", encoding="utf-8-sig")
    github_output = config_file.parent / "gh_output"
    result = runner.invoke(
        app,
        [
            "ci", "plan", "--changed-files", str(changed), "--repo-root", str(config_file.parent),
            "--github-output", str(github_output), "-c", config,
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "Evaluate: v2 against baseline 'main'" in result.output
    plan = CiPlan.model_validate_json(Path("ci-plan.json").read_text(encoding="utf-8"))
    assert plan.prompt_versions == ("v2",)
    assert github_output.read_text(encoding="utf-8").splitlines() == [
        "evaluate=true",
        "relevant=true",
        "prompts=v2",
    ]


def test_cli_run_cases_from_baseline_then_summarize(config: str) -> None:  # noqa: F811
    first = runner.invoke(app, ["run", "-p", "v1", "--limit", "8", "-c", config])
    assert first.exit_code == 0, first.output
    run_id = runner.invoke(app, ["runs", "list"]).stdout.split()[0]
    assert runner.invoke(app, ["baseline", "promote", run_id, "-c", config]).exit_code == 0

    second = runner.invoke(
        app,
        [
            "run",
            "-p",
            "v2",
            "--baseline",
            "main",
            "--cases-from-baseline",
            "--no-judge",
            "-c",
            config,
        ],
    )
    assert "8 case(s)" in second.output  # exactly the baseline's cases, not the whole dataset

    Path("ci-plan.json").write_text(
        CiPlan(prompt_versions=("v2",)).model_dump_json(), encoding="utf-8"
    )
    summary = runner.invoke(app, ["ci", "summarize", "-c", config])
    assert summary.exit_code == 0, summary.output  # mock answers do not depend on the prompt
    assert "GATE: PASS" in summary.output
    assert Path("pr-comment.md").read_text(encoding="utf-8").startswith(COMMENT_MARKER)


def test_cli_baseline_prompt(config: str) -> None:  # noqa: F811
    missing = runner.invoke(app, ["ci", "baseline-prompt", "-c", config])
    assert missing.exit_code == EXIT_CONFIG_ERROR
    _baseline(Path(config).parent / "baselines", prompt_version="v7")
    shown = runner.invoke(app, ["ci", "baseline-prompt", "-c", config])
    assert shown.exit_code == 0 and shown.stdout == "v7\n"


def test_cli_cases_from_baseline_needs_baseline(config: str) -> None:  # noqa: F811
    result = runner.invoke(app, ["run", "-p", "v1", "--cases-from-baseline", "-c", config])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "--cases-from-baseline needs --baseline" in result.output


def test_cli_summarize_exit_codes(config: str) -> None:  # noqa: F811
    Path("ci-plan.json").write_text(CiPlan().model_dump_json(), encoding="utf-8")
    nothing = runner.invoke(app, ["ci", "summarize", "-c", config])
    assert nothing.exit_code == 0 and "NOTHING TO EVALUATE" in nothing.output

    Path("ci-plan.json").write_text(
        CiPlan(prompt_versions=("v9",)).model_dump_json(), encoding="utf-8"
    )
    missing = runner.invoke(app, ["ci", "summarize", "-c", config])
    assert missing.exit_code == EXIT_PROVIDER_ERROR and "GATE: ERROR" in missing.output

    Path("ci-plan.json").write_text(CiPlan(blocking="no").model_dump_json(), encoding="utf-8")
    blocked = runner.invoke(app, ["ci", "summarize", "-c", config])
    assert blocked.exit_code == EXIT_GATE_FAILED

    unreadable = runner.invoke(app, ["ci", "summarize", "--plan", "nope.json", "-c", config])
    assert unreadable.exit_code == EXIT_CONFIG_ERROR
