"""Baseline file store and the promote / compare services."""

import json
from pathlib import Path

import pytest

from regguard.apps.config import AppConfig
from regguard.core.errors import ComparisonError, DataValidationError
from regguard.core.types import RunStatus, Verdict
from regguard.services.compare_service import compare_with_baseline, promote_baseline
from regguard.storage.baseline_store import baseline_path, list_baselines, load_baseline
from regguard.storage.file_store import save_run
from tests.unit.run_factory import make_run, outcomes


@pytest.fixture
def cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        name="t",
        app="support_email_classifier",
        prompts_dir=tmp_path / "prompts",
        baselines_dir=tmp_path / "baselines",
    )


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def test_promote_then_load_and_list(cfg: AppConfig, runs: Path) -> None:
    save_run(runs, make_run(outcomes(4), run_id="20261112T000000Z-aaaaaa"))
    baseline, path = promote_baseline(
        cfg, runs, "20261112T0000", note="v1 reviewed", git_revision="abc"
    )
    assert path == cfg.baselines_dir / "main.json"
    assert baseline.header.source_run_id == "20261112T000000Z-aaaaaa"
    loaded = load_baseline(cfg.baselines_dir, "main")
    assert loaded == baseline
    assert loaded.header.note == "v1 reviewed"
    assert [b.header.name for b in list_baselines(cfg.baselines_dir)] == ["main"]
    assert json.loads(path.read_text(encoding="utf-8"))["header"]["git_sha"] == "abc"


def test_overwrite_needs_replace(cfg: AppConfig, runs: Path) -> None:
    save_run(runs, make_run(outcomes(4), run_id="r1"))
    save_run(runs, make_run(outcomes(4), run_id="r2"))
    promote_baseline(cfg, runs, "r1")
    with pytest.raises(DataValidationError, match="--replace"):
        promote_baseline(cfg, runs, "r2")
    baseline, _ = promote_baseline(cfg, runs, "r2", replace=True)
    assert baseline.header.source_run_id == "r2"


def test_errored_run_cannot_be_promoted(cfg: AppConfig, runs: Path) -> None:
    save_run(runs, make_run(outcomes(4), run_id="r1", status=RunStatus.ERROR))
    with pytest.raises(ComparisonError, match="only completed runs"):
        promote_baseline(cfg, runs, "r1")


def test_run_of_another_app_cannot_be_promoted(cfg: AppConfig, runs: Path) -> None:
    save_run(runs, make_run(outcomes(4), run_id="r1", app="other"))
    with pytest.raises(ComparisonError, match="belongs to app 'other'"):
        promote_baseline(cfg, runs, "r1")


@pytest.mark.parametrize("name", ["Main", "../evil", "", "a b"])
def test_invalid_baseline_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(DataValidationError, match="Invalid baseline name"):
        baseline_path(tmp_path, name)


def test_missing_baseline_explains_how_to_create(cfg: AppConfig) -> None:
    with pytest.raises(DataValidationError, match="baseline promote"):
        load_baseline(cfg.baselines_dir, "main")


def test_list_without_directory_is_empty(cfg: AppConfig) -> None:
    assert list_baselines(cfg.baselines_dir) == []


def test_compare_with_named_baseline_saves_comparison(cfg: AppConfig, runs: Path) -> None:
    save_run(runs, make_run(outcomes(30), run_id="base"))
    promote_baseline(cfg, runs, "base")
    candidate = make_run(outcomes(30, fail=[1, 2, 3]), run_id="cand")
    save_run(runs, candidate)
    comparison, path = compare_with_baseline(cfg, runs, candidate)
    assert comparison.verdict is Verdict.FAIL
    assert comparison.baseline_name == "main"
    assert path == runs / "cand" / "comparison-main.json"
    assert path.is_file()


def test_compare_against_a_run_directly(cfg: AppConfig, runs: Path) -> None:
    save_run(runs, make_run(outcomes(12), run_id="base"))
    candidate = make_run(outcomes(12), run_id="cand")
    comparison, path = compare_with_baseline(cfg, runs, candidate, against_run="base")
    assert comparison.verdict is Verdict.PASS
    assert comparison.baseline_name is None
    assert path.name == "comparison-base.json"


def test_compare_needs_a_reference(cfg: AppConfig, runs: Path) -> None:
    with pytest.raises(ComparisonError, match="baseline name or a run id"):
        compare_with_baseline(cfg, runs, make_run(outcomes(2)), baseline_name=None)
