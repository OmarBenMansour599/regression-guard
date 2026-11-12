"""CLI: baseline promote/list/show, compare, and run --baseline (mock provider, no network)."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from regguard.cli.main import EXIT_CONFIG_ERROR, EXIT_GATE_FAILED, EXIT_PROVIDER_ERROR, app
from regguard.core.types import RunStatus
from regguard.storage.baseline_store import load_baseline
from regguard.storage.file_store import save_run
from tests.unit.run_factory import make_run, outcomes
from tests.unit.test_cli_run import config  # noqa: F401 - pytest fixture

runner = CliRunner()


def _save(run_id: str, fail: list[int], **kwargs: Any) -> None:
    save_run(Path("runs"), make_run(outcomes(30, fail=fail), run_id=run_id, **kwargs))


def test_run_promote_then_run_with_baseline_passes(config: str) -> None:  # noqa: F811
    first = runner.invoke(app, ["run", "-p", "v1", "-c", config])
    assert first.exit_code == 0, first.output
    run_id = runner.invoke(app, ["runs", "list"]).stdout.split()[0]

    promoted = runner.invoke(app, ["baseline", "promote", run_id, "--note", "first", "-c", config])
    assert promoted.exit_code == 0, promoted.output
    baseline = load_baseline(Path(config).parent / "baselines", "main")
    assert baseline.run.meta.case_labels  # runner now records golden labels
    assert baseline.header.note == "first"

    second = runner.invoke(app, ["run", "-p", "v1", "--baseline", "main", "-c", config])
    assert second.exit_code == 0, second.output
    assert "VERDICT: PASS" in second.output
    assert "comparison-main.json" in second.output

    listing = runner.invoke(app, ["baseline", "list", "-c", config])
    assert "main" in listing.output and run_id in listing.output
    shown = runner.invoke(app, ["baseline", "show", "-c", config])
    assert shown.exit_code == 0, shown.output
    assert "note: first" in shown.output


def test_run_with_missing_baseline_fails_before_any_call(config: str) -> None:  # noqa: F811
    result = runner.invoke(app, ["run", "-p", "v1", "--baseline", "nope", "-c", config])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "baseline promote" in result.output
    assert "done" not in result.output  # nothing was executed


def test_compare_fail_exits_4(config: str) -> None:  # noqa: F811
    _save("base", [])
    _save("cand", [1, 2, 3])
    assert runner.invoke(app, ["baseline", "promote", "base", "-c", config]).exit_code == 0
    result = runner.invoke(app, ["compare", "cand", "-c", config])
    assert result.exit_code == EXIT_GATE_FAILED, result.output
    assert "VERDICT: FAIL" in result.output
    assert "critical_regression" in result.output
    assert "REGRESSED" in result.output


def test_compare_warn_exits_0_unless_fail_on_warn(config: str) -> None:  # noqa: F811
    _save("base", [])
    _save("cand", [2])  # 1 regression of 30: -3.3 pts (warn), too few cases for FAIL
    runner.invoke(app, ["baseline", "promote", "base", "-c", config])
    assert runner.invoke(app, ["compare", "cand", "-c", config]).exit_code == 0
    strict = runner.invoke(app, ["compare", "cand", "--fail-on-warn", "-c", config])
    assert strict.exit_code == EXIT_GATE_FAILED
    assert "VERDICT: WARN" in strict.output


def test_compare_against_run_and_show_all(config: str) -> None:  # noqa: F811
    _save("base", [])
    _save("cand", [])
    result = runner.invoke(app, ["compare", "cand", "--against", "base", "--all", "-c", config])
    assert result.exit_code == 0, result.output
    assert "STILL_PASS" in result.output


def test_compare_errored_candidate_exits_3(config: str) -> None:  # noqa: F811
    _save("base", [])
    _save("cand", [1, 2, 3, 4, 5], status=RunStatus.ERROR)
    runner.invoke(app, ["baseline", "promote", "base", "-c", config])
    result = runner.invoke(app, ["compare", "cand", "-c", config])
    assert result.exit_code == EXIT_PROVIDER_ERROR
    assert "VERDICT: ERROR" in result.output


def test_dataset_change_is_refused_by_default(config: str) -> None:  # noqa: F811
    _save("base", [])
    _save("cand", [], dataset_hash="sha256:" + "c" * 64)
    runner.invoke(app, ["baseline", "promote", "base", "-c", config])
    refused = runner.invoke(app, ["compare", "cand", "-c", config])
    assert refused.exit_code == EXIT_CONFIG_ERROR
    allowed = runner.invoke(app, ["compare", "cand", "--allow-dataset-change", "-c", config])
    assert allowed.exit_code == 0
    assert "dataset_changed" in allowed.output


@pytest.mark.parametrize(
    "args",
    [
        ["compare", "missing"],
        ["baseline", "show", "missing"],
        ["baseline", "promote", "missing"],
    ],
)
def test_missing_things_are_config_errors(config: str, args: list[str]) -> None:  # noqa: F811
    result = runner.invoke(app, [*args, "-c", config])
    assert result.exit_code == EXIT_CONFIG_ERROR


def test_baseline_list_empty(config: str) -> None:  # noqa: F811
    assert "No baselines" in runner.invoke(app, ["baseline", "list", "-c", config]).output
