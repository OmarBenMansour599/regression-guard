"""History database: migrations and repository.

Runs on SQLite always. Set REGGUARD_TEST_DATABASE_URL (CI does, with a PostgreSQL service
container) to run the same tests against PostgreSQL too. That database is wiped.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from regguard.core.errors import ConfigError
from regguard.core.types import Comparison, Verdict
from regguard.storage.db.models import Base, CaseResultRow, RunMetricRow
from regguard.storage.db.repository import HistoryRepository
from regguard.storage.db.session import (
    current_revision,
    downgrade,
    head_revision,
    make_engine,
    open_history,
    upgrade,
)
from tests.unit.run_factory import make_run, outcomes

TABLES = {"eval_run", "run_metric", "case_result", "comparison"}
POSTGRES_URL = os.environ.get("REGGUARD_TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    """An empty database (no schema) on each backend that is available."""
    if request.param == "postgres":
        if not POSTGRES_URL:
            pytest.skip("REGGUARD_TEST_DATABASE_URL not set (PostgreSQL runs in CI)")
        eng = make_engine(POSTGRES_URL)
        if current_revision(eng) is not None:
            downgrade(eng, "base")
    else:
        eng = make_engine(f"sqlite:///{tmp_path / 'history.db'}")
    yield eng
    eng.dispose()


@pytest.fixture
def repo(engine: Engine) -> HistoryRepository:
    upgrade(engine)
    return HistoryRepository(engine)


# --- migrations -----------------------------------------------------------------------------


def test_migrations_up_down_up(engine: Engine) -> None:
    upgrade(engine)
    assert current_revision(engine) == head_revision()
    assert set(inspect(engine).get_table_names()) >= TABLES

    downgrade(engine, "base")
    assert current_revision(engine) is None
    assert not TABLES & set(inspect(engine).get_table_names())

    upgrade(engine)
    assert current_revision(engine) == head_revision()


def test_migrations_produce_exactly_the_models_schema(engine: Engine) -> None:
    upgrade(engine)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_open_history_creates_and_upgrades_local_sqlite(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'new' / 'dir' / 'history.db'}"  # parent dirs created
    engine = open_history(url)
    assert current_revision(engine) == head_revision()
    engine.dispose()


def test_open_history_refuses_an_outdated_schema_without_auto_upgrade(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="regguard db upgrade"):
        open_history(f"sqlite:///{tmp_path / 'h.db'}", auto_upgrade_sqlite=False)


# --- repository -----------------------------------------------------------------------------


def run_at(run_id: str, day: int, *, app: str = "t", fail: tuple[int, ...] = ()):  # type: ignore[no-untyped-def]
    run = make_run(outcomes(4, fail=fail), run_id=run_id, app=app)
    meta = run.meta.model_copy(
        update={"started_at": datetime(2026, 11, 1, tzinfo=UTC) + timedelta(days=day)}
    )
    return run.model_copy(update={"meta": meta})


def test_save_and_load_run_round_trip(repo: HistoryRepository) -> None:
    run = run_at("r1", 0, fail=(2,))
    assert repo.save_run(run) is True
    assert repo.save_run(run) is False  # idempotent
    assert repo.has_run("r1")
    assert repo.get_run("r1") == run
    assert repo.get_run("missing") is None
    assert repo.count_runs() == 1


def test_metrics_and_cases_are_queryable(repo: HistoryRepository) -> None:
    run = run_at("r1", 0, fail=(2,))
    repo.save_run(run)
    with Session(repo.engine) as session:
        metrics = {m.name: m.value for m in session.scalars(select(RunMetricRow))}
        cases = {c.case_id: c for c in session.scalars(select(CaseResultRow))}
    assert metrics.keys() == run.aggregates.keys()
    assert metrics["schema_valid"] == 1.0
    assert len(cases) == 4
    assert cases["email-0002"].passed is False
    assert cases["email-0001"].label == "billing"


def test_list_and_series_are_ordered_and_filtered(repo: HistoryRepository) -> None:
    repo.save_run(run_at("r2", 2))
    repo.save_run(run_at("r1", 1))
    repo.save_run(run_at("r3", 3, app="other"))

    assert [r.run_id for r in repo.list_runs()] == ["r3", "r2", "r1"]  # newest first
    assert [r.run_id for r in repo.list_runs(app="t")] == ["r2", "r1"]
    assert [r.run_id for r in repo.list_runs(limit=1)] == ["r3"]

    series = repo.metric_series("schema_valid", app="t")
    assert [(r.run_id, v) for r, v in series] == [("r1", 1.0), ("r2", 1.0)]  # oldest first
    assert [r.meta.run_id for r in repo.load_runs(app="t")] == ["r1", "r2"]


def test_comparison_is_stored_and_replaced(repo: HistoryRepository) -> None:
    repo.save_run(run_at("cand", 1))
    first = Comparison(
        app="t",
        baseline_run_id="base",
        baseline_name="main",
        candidate_run_id="cand",
        verdict=Verdict.WARN,
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    repo.save_comparison(first)
    repo.save_comparison(first.model_copy(update={"verdict": Verdict.PASS}))
    assert [c.verdict for c in repo.comparisons_for("cand")] == [Verdict.PASS]
