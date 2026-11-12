from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from regguard.apps.config import AppConfig, load_app_config
from regguard.core.config import Settings
from regguard.core.errors import DataValidationError
from regguard.core.types import RunStatus
from regguard.providers.mock_provider import MockProvider
from regguard.services.run_service import (
    BudgetExceededError,
    RunOptions,
    check_budget,
    execute_prepared,
    prepare_run,
)
from regguard.storage.file_store import list_runs, load_run, new_run_id
from tests.conftest import EXAMPLE_APP
from tests.unit.test_datasets import balanced_cases, write_dataset

VALID = '{"category": "billing", "summary": "Customer writes about billing."}'


def _config(tmp_path: Path) -> AppConfig:
    write_dataset(tmp_path / "datasets", balanced_cases(per_category=3))
    path = tmp_path / "regguard.yaml"
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
    return load_app_config(path)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="mock",
        cache_dir=tmp_path / "cache",
        runs_dir=tmp_path / "runs",
        requests_per_minute=10_000,
    )


def test_prepare_counts_calls_and_selects(tmp_path: Path) -> None:
    prepared = prepare_run(
        _config(tmp_path),
        RunOptions(prompt_version="v1", limit=4, n_samples=2),
        _settings(tmp_path),
        provider_name="mock",
    )
    assert len(prepared.plan.cases) == 4
    assert prepared.plan.total_calls == 8
    assert prepared.uncached_calls == 8
    assert prepared.plan.selection.limit == 4


def test_budget_guard(tmp_path: Path) -> None:
    prepared = prepare_run(
        _config(tmp_path),
        RunOptions(prompt_version="v1", max_requests=5),
        _settings(tmp_path),
        provider_name="mock",
    )
    with pytest.raises(BudgetExceededError, match="12 API call"):
        check_budget(prepared)


async def test_execute_saves_and_second_run_is_free(tmp_path: Path) -> None:
    config, settings = _config(tmp_path), _settings(tmp_path)
    options = RunOptions(prompt_version="v1")

    first = await execute_prepared(
        prepare_run(config, options, settings, provider_name="mock"), MockProvider(VALID), settings
    )
    assert first.status is RunStatus.COMPLETED
    assert first.meta.execution.api_calls == 12
    assert first.aggregates["label_exact"].value == 0.25  # mock always says "billing"

    again = prepare_run(config, options, settings, provider_name="mock")
    assert again.uncached_calls == 0
    second = await execute_prepared(again, MockProvider(VALID), settings)
    assert second.meta.execution.api_calls == 0

    assert load_run(settings.runs_dir, first.meta.run_id) == first
    assert [r.meta.run_id for r in list_runs(settings.runs_dir)] == [
        second.meta.run_id,
        first.meta.run_id,
    ]


def test_unknown_prompt_version(tmp_path: Path) -> None:
    with pytest.raises(DataValidationError, match="v9"):
        prepare_run(
            _config(tmp_path),
            RunOptions(prompt_version="v9"),
            _settings(tmp_path),
            provider_name="mock",
        )


def test_run_id_format_and_prefix_lookup(tmp_path: Path) -> None:
    run_id = new_run_id(datetime(2026, 11, 12, 15, 30, tzinfo=UTC))
    assert run_id.startswith("20261112T153000Z-")
    with pytest.raises(DataValidationError, match="No runs"):
        load_run(tmp_path / "nothing", run_id)
