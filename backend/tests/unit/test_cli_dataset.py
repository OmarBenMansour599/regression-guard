from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from regguard.cli.main import EXIT_CONFIG_ERROR, EXIT_VALIDATION_FAILED, app
from tests.conftest import EXAMPLE_APP
from tests.unit.test_datasets import balanced_cases, make_case, write_dataset

runner = CliRunner()

pytestmark = pytest.mark.usefixtures("isolated_env")


def _app_dir(tmp_path: Path, cases: list[dict[str, object]]) -> str:
    write_dataset(tmp_path / "datasets", cases)
    config = {
        "name": "t",
        "app": "support_email_classifier",
        "prompts_dir": str(EXAMPLE_APP / "prompts" / "classify"),
        "datasets_dir": "datasets",
    }
    path = tmp_path / "regguard.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(path)


def test_validate_ok_with_warnings(tmp_path: Path) -> None:
    result = runner.invoke(app, ["dataset", "validate", "-c", _app_dir(tmp_path, balanced_cases())])
    assert result.exit_code == 0, result.output
    assert "12 cases" in result.output
    assert "too_few_cases" in result.output


def test_validate_strict_fails_on_warnings(tmp_path: Path) -> None:
    config = _app_dir(tmp_path, balanced_cases())
    result = runner.invoke(app, ["dataset", "validate", "--strict", "-c", config])
    assert result.exit_code == EXIT_VALIDATION_FAILED


def test_validate_strict_passes_clean_dataset(tmp_path: Path) -> None:
    config = _app_dir(tmp_path, balanced_cases())
    result = runner.invoke(
        app, ["dataset", "validate", "--strict", "--min-cases", "12", "-c", config]
    )
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_validate_reports_invalid_cases(tmp_path: Path) -> None:
    config = _app_dir(tmp_path, [make_case(1, "refunds")])
    result = runner.invoke(app, ["dataset", "validate", "-c", config])
    assert result.exit_code == EXIT_VALIDATION_FAILED
    assert "email-0001" in result.output


def test_stats_and_list(tmp_path: Path) -> None:
    config = _app_dir(tmp_path, balanced_cases())
    stats = runner.invoke(app, ["dataset", "stats", "-c", config])
    assert stats.exit_code == 0, stats.output
    assert "billing" in stats.output
    listing = runner.invoke(app, ["dataset", "list", "-c", config])
    assert listing.stdout.strip() == "v1"


def test_committed_golden_dataset_is_valid() -> None:
    """Guards the real golden dataset: every committed case must load and validate."""
    config = str(EXAMPLE_APP / "regguard.yaml")
    result = runner.invoke(app, ["dataset", "validate", "-c", config])
    assert result.exit_code == 0, result.output


def test_empty_cases_file_reports_no_cases_yet(tmp_path: Path) -> None:
    config = _app_dir(tmp_path, [])
    result = runner.invoke(app, ["dataset", "validate", "-c", config])
    assert result.exit_code == EXIT_VALIDATION_FAILED
    assert "no cases yet" in result.output


def test_missing_datasets_dir(tmp_path: Path) -> None:
    path = tmp_path / "regguard.yaml"
    path.write_text(
        yaml.safe_dump({"name": "t", "app": "support_email_classifier", "prompts_dir": "p"}),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["dataset", "validate", "-c", str(path)])
    assert result.exit_code == EXIT_CONFIG_ERROR
