"""History service and CLI: recording, import, list, trend, drift, db upgrade."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from regguard.cli.main import EXIT_GATE_FAILED, app
from regguard.core.config import Settings
from regguard.core.types import AggregateScore, ExecutionStats, RunResult
from regguard.services.history_service import (
    history,
    import_runs,
    list_history,
    record_run,
)
from regguard.storage.file_store import save_run
from tests.unit.run_factory import make_run, outcomes
from tests.unit.test_cli_run import config  # noqa: F401 - pytest fixture

runner = CliRunner()


def settings_for(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_provider": "mock",
        "runs_dir": tmp_path / "runs",
        "database_url": f"sqlite:///{tmp_path / 'history.db'}",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


# --- service --------------------------------------------------------------------------------


def test_record_run_then_list(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    run = make_run(outcomes(4), run_id="r1")
    assert record_run(settings, run) is None
    assert record_run(settings, run) is None  # recording twice is harmless
    assert [r.run_id for r in list_history(settings, app=None, limit=10)] == ["r1"]


def test_recording_can_be_disabled(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, record_history=False)
    assert record_run(settings, make_run(outcomes(4))) is None
    assert not (tmp_path / "history.db").exists()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user:pw@127.0.0.1:1/none",  # driver missing, or nothing listening
        "nosuchdialect://x",
    ],
)
def test_a_broken_database_is_a_warning_not_a_failure(tmp_path: Path, url: str) -> None:
    warning = record_run(settings_for(tmp_path, database_url=url), make_run(outcomes(4)))
    assert warning is not None
    assert "not recorded in history" in warning
    assert "result file is saved" in warning


def test_import_runs_is_idempotent_and_reports_bad_files(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    save_run(settings.runs_dir, make_run(outcomes(4), run_id="r1"))
    save_run(settings.runs_dir, make_run(outcomes(4), run_id="r2"))
    (settings.runs_dir / "r2" / "comparison-main.json").write_text(
        '{"app": "t", "baseline_run_id": "b", "baseline_name": "main", '
        '"candidate_run_id": "r2", "verdict": "pass", "created_at": "2026-11-18T00:00:00Z"}',
        encoding="utf-8",
    )
    broken = settings.runs_dir / "r3"
    broken.mkdir()
    (broken / "result.json").write_text("{not json", encoding="utf-8")

    first = import_runs(settings)
    assert (first.imported, first.skipped, first.comparisons) == (2, 0, 1)
    assert len(first.failed) == 1
    second = import_runs(settings)
    assert (second.imported, second.skipped) == (0, 2)


def test_import_without_runs_dir(tmp_path: Path) -> None:
    assert import_runs(settings_for(tmp_path)).imported == 0


# --- CLI --------------------------------------------------------------------------------------


def test_cli_run_is_recorded_then_listed_and_trended(config: str) -> None:  # noqa: F811
    assert runner.invoke(app, ["run", "-p", "v1", "-c", config]).exit_code == 0
    listing = runner.invoke(app, ["history", "list"])
    assert listing.exit_code == 0, listing.output
    assert "v1" in listing.output
    assert "fresh" in listing.output  # first run: real (mock) calls, no cache

    trend = runner.invoke(app, ["history", "trend", "-m", "label_exact"])
    assert trend.exit_code == 0, trend.output
    assert "0.250" in trend.output  # the mock always answers "billing": 3 of 12

    assert "No values" in runner.invoke(app, ["history", "trend", "-m", "nope"]).output


def test_cli_compare_is_recorded(config: str) -> None:  # noqa: F811
    runner.invoke(app, ["run", "-p", "v1", "-c", config])
    run_id = runner.invoke(app, ["runs", "list"]).stdout.split()[0]
    runner.invoke(app, ["baseline", "promote", run_id, "-c", config])
    runner.invoke(app, ["compare", run_id, "-c", config])
    with history(Settings()) as repo:
        assert [c.baseline_name for c in repo.comparisons_for(run_id)] == ["main"]


def test_cli_history_empty_and_db_upgrade(isolated_env: Path) -> None:
    assert "No runs in history" in runner.invoke(app, ["history", "list"]).output
    upgraded = runner.invoke(app, ["db", "upgrade"])
    assert upgraded.exit_code == 0, upgraded.output
    assert "already at revision" in upgraded.output  # `history list` created it


def test_cli_db_upgrade_on_a_fresh_database(isolated_env: Path) -> None:
    result = runner.invoke(app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert "empty -> 0001" in result.output


def test_cli_history_import(isolated_env: Path) -> None:
    save_run(Path("runs"), make_run(outcomes(4), run_id="r1"))
    result = runner.invoke(app, ["history", "import"])
    assert result.exit_code == 0, result.output
    assert "Imported 1 run(s), 0 already present" in result.output


def fresh_run(base: RunResult, day: int, label: float) -> RunResult:
    meta = base.meta.model_copy(
        update={
            "run_id": f"mon-{day:02d}",
            "started_at": base.meta.started_at + timedelta(days=day),
            "execution": ExecutionStats(api_calls=30),
        }
    )
    aggregates = {**base.aggregates, "label_exact": AggregateScore(value=label, n=30)}
    return base.model_copy(update={"meta": meta, "aggregates": aggregates})


def test_cli_drift_insufficient_then_drift(config: str) -> None:  # noqa: F811
    base = make_run(outcomes(30), run_id="base")
    base = base.model_copy(
        update={"aggregates": {**base.aggregates, "label_exact": AggregateScore(value=0.9, n=30)}}
    )
    save_run(Path("runs"), base)
    assert runner.invoke(app, ["baseline", "promote", "base", "-c", config]).exit_code == 0

    early = runner.invoke(app, ["drift", "-c", config])
    assert early.exit_code == 0, early.output
    assert "DRIFT STATUS: INSUFFICIENT" in early.output
    assert "--cache refresh" in early.output

    settings = Settings()
    for day, value in enumerate([0.9, 0.8, 0.8, 0.8], start=1):
        assert record_run(settings, fresh_run(base, day, value)) is None

    report = runner.invoke(app, ["drift", "-c", config])
    assert report.exit_code == 0, report.output  # no --fail-on-drift: report only
    assert "DRIFT STATUS: DRIFT" in report.output
    assert "[NEW EPISODE]" in report.output
    assert "4 comparable run(s), 4 fresh" in report.output

    failing = runner.invoke(app, ["drift", "--fail-on-drift", "-c", config])
    assert failing.exit_code == EXIT_GATE_FAILED


def test_cli_drift_without_baseline_is_a_config_error(config: str) -> None:  # noqa: F811
    result = runner.invoke(app, ["drift", "-c", config])
    assert result.exit_code == 2
    assert "baseline promote" in result.output


def test_history_timestamps_survive_the_database(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    run = make_run(outcomes(2), run_id="r1")
    meta = run.meta.model_copy(update={"started_at": datetime(2026, 11, 18, 9, 30, tzinfo=UTC)})
    record_run(settings, run.model_copy(update={"meta": meta}))
    with history(settings) as repo:
        loaded = repo.get_run("r1")
    assert loaded is not None
    assert loaded.meta.started_at == meta.started_at  # full JSON keeps the timezone
