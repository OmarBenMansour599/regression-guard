import json

import pytest
from typer.testing import CliRunner

from regguard import __version__
from regguard.cli.main import EXIT_CONFIG_ERROR, app
from tests.conftest import EXAMPLE_APP

runner = CliRunner()
CONFIG = str(EXAMPLE_APP / "regguard.yaml")

pytestmark = pytest.mark.usefixtures("isolated_env")


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"regguard {__version__}"


def test_no_args_shows_help() -> None:
    assert "Usage" in runner.invoke(app, []).stdout


def test_prompt_list() -> None:
    result = runner.invoke(app, ["prompt", "list", "-c", CONFIG])
    assert result.exit_code == 0, result.output
    assert "v1" in result.stdout
    assert "v2" in result.stdout
    assert "sha256:" in result.stdout


def test_prompt_show() -> None:
    result = runner.invoke(app, ["prompt", "show", "v1", "-c", CONFIG])
    assert result.exit_code == 0, result.output
    assert "few-shot:  2 example(s)" in result.stdout


def test_try_with_mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_LLM_PROVIDER", "mock")
    result = runner.invoke(app, ["try", "-c", CONFIG, "-p", "v1", "-i", "I was charged twice"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["schema_valid"] is True
    assert report["output"]["category"] == "billing"
    assert report["provider"] == "mock"
    assert report["prompt"] == "classify@v1"


def test_try_without_api_key_is_config_error() -> None:
    result = runner.invoke(app, ["try", "-c", CONFIG, "-p", "v1", "-i", "x"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "REGGUARD_LLM_API_KEY" in result.output


def test_try_requires_exactly_one_input() -> None:
    result = runner.invoke(app, ["try", "-c", CONFIG, "-p", "v1"])
    assert result.exit_code == EXIT_CONFIG_ERROR


def test_try_unknown_prompt_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGGUARD_LLM_PROVIDER", "mock")
    result = runner.invoke(app, ["try", "-c", CONFIG, "-p", "v99", "-i", "x"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "v99" in result.output
