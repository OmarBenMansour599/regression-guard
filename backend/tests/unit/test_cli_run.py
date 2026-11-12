from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from regguard.cli.main import EXIT_CONFIG_ERROR, app
from tests.conftest import EXAMPLE_APP
from tests.unit.test_datasets import balanced_cases, write_dataset

runner = CliRunner()


@pytest.fixture
def config(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("REGGUARD_LLM_PROVIDER", "mock")
    monkeypatch.setenv("REGGUARD_REQUESTS_PER_MINUTE", "10000")
    write_dataset(isolated_env / "datasets", balanced_cases())
    path = isolated_env / "regguard.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "t",
                "app": "support_email_classifier",
                "prompts_dir": str(EXAMPLE_APP / "prompts" / "classify"),
                "datasets_dir": "datasets",
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_run_then_list_and_show(config: str) -> None:
    result = runner.invoke(app, ["run", "-p", "v1", "-c", config])
    assert result.exit_code == 0, result.output
    assert "12 call(s), 0 cached" in result.output
    assert "COMPLETED" in result.output
    assert "label_exact/billing" in result.output

    listing = runner.invoke(app, ["runs", "list"])
    assert listing.exit_code == 0, listing.output
    run_id = listing.stdout.split()[0]

    shown = runner.invoke(app, ["runs", "show", run_id[:16]])
    assert shown.exit_code == 0, shown.output
    assert "FAIL" in shown.output  # mock always answers billing: other labels fail


def test_second_run_uses_cache(config: str) -> None:
    runner.invoke(app, ["run", "-p", "v1", "-c", config])
    result = runner.invoke(app, ["run", "-p", "v1", "-c", config])
    assert "12 cached" in result.output
    assert "0 api, 12 cached" in result.output


def test_budget_refusal(config: str) -> None:
    result = runner.invoke(app, ["run", "-p", "v1", "--max-requests", "3", "-c", config])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "--max-requests" in result.output


def test_limit_runs_subset(config: str) -> None:
    result = runner.invoke(app, ["run", "-p", "v1", "--limit", "4", "-c", config])
    assert result.exit_code == 0, result.output
    assert "4 case(s)" in result.output


def test_runs_list_empty(isolated_env: Path) -> None:
    result = runner.invoke(app, ["runs", "list"])
    assert "No runs" in result.output
