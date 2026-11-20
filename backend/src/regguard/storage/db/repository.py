"""Read and write run history. All database access goes through this class."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from regguard.core.types import Comparison, RunResult
from regguard.storage.db.models import CaseResultRow, ComparisonRow, EvalRunRow, RunMetricRow


@dataclass(frozen=True)
class RunRecord:
    """A run's headline facts, without parsing its full JSON."""

    run_id: str
    app: str
    prompt_version: str
    dataset_version: str
    model: str
    status: str
    trigger: str
    started_at: datetime
    n_cases: int
    api_calls: int
    cache_hits: int


def _record(row: EvalRunRow) -> RunRecord:
    return RunRecord(
        run_id=row.run_id,
        app=row.app,
        prompt_version=row.prompt_version,
        dataset_version=row.dataset_version,
        model=row.model,
        status=row.status,
        trigger=row.trigger,
        started_at=row.started_at,
        n_cases=row.n_cases,
        api_calls=row.api_calls,
        cache_hits=row.cache_hits,
    )


def _run_rows(result: RunResult) -> tuple[EvalRunRow, list[RunMetricRow], list[CaseResultRow]]:
    m = result.meta
    run = EvalRunRow(
        run_id=m.run_id,
        app=m.app,
        prompt_version=m.prompt_version,
        prompt_hash=m.prompt_hash,
        dataset_version=m.dataset_version,
        dataset_hash=m.dataset_hash,
        provider=m.provider,
        model=m.model,
        judge_hash=(m.judge or {}).get("prompt_hash"),
        trigger=m.trigger.value,
        status=result.status.value,
        git_sha=m.git_sha,
        started_at=m.started_at,
        finished_at=m.finished_at,
        n_cases=len({c.case_id for c in result.cases}),
        api_calls=m.execution.api_calls,
        cache_hits=m.execution.cache_hits,
        result_json=result.model_dump_json(),
    )
    metrics = [
        RunMetricRow(run_id=m.run_id, name=name, value=agg.value, n=agg.n)
        for name, agg in result.aggregates.items()
    ]
    cases = [
        CaseResultRow(
            run_id=m.run_id,
            case_id=c.case_id,
            sample_idx=c.sample_idx,
            passed=c.passed,
            error_type=c.error.type if c.error else None,
            label=m.case_labels.get(c.case_id),
            judge_score=c.judge.score if c.judge else None,
        )
        for c in result.cases
    ]
    return run, metrics, cases


class HistoryRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def has_run(self, run_id: str) -> bool:
        with Session(self.engine) as session:
            return session.get(EvalRunRow, run_id) is not None

    def save_run(self, result: RunResult) -> bool:
        """Store a run with its metrics and cases. Returns False if it was already stored."""
        with Session(self.engine) as session, session.begin():
            if session.get(EvalRunRow, result.meta.run_id) is not None:
                return False
            run, metrics, cases = _run_rows(result)
            session.add(run)
            session.flush()  # parent row first: children reference it
            session.add_all([*metrics, *cases])
        return True

    def get_run(self, run_id: str) -> RunResult | None:
        with Session(self.engine) as session:
            row = session.get(EvalRunRow, run_id)
            return None if row is None else RunResult.model_validate_json(row.result_json)

    def save_comparison(self, comparison: Comparison) -> None:
        """Store a comparison (the candidate run must be stored). Replaces the same pair."""
        with Session(self.engine) as session, session.begin():
            session.execute(
                delete(ComparisonRow).where(
                    ComparisonRow.candidate_run_id == comparison.candidate_run_id,
                    ComparisonRow.baseline_run_id == comparison.baseline_run_id,
                )
            )
            session.add(
                ComparisonRow(
                    candidate_run_id=comparison.candidate_run_id,
                    baseline_run_id=comparison.baseline_run_id,
                    baseline_name=comparison.baseline_name,
                    verdict=comparison.verdict.value,
                    created_at=comparison.created_at,
                    comparison_json=comparison.model_dump_json(),
                )
            )

    def comparisons_for(self, candidate_run_id: str) -> list[Comparison]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ComparisonRow)
                .where(ComparisonRow.candidate_run_id == candidate_run_id)
                .order_by(ComparisonRow.created_at)
            )
            return [Comparison.model_validate_json(r.comparison_json) for r in rows]

    def list_runs(self, *, app: str | None = None, limit: int = 20) -> list[RunRecord]:
        """Newest first."""
        query = select(EvalRunRow).order_by(EvalRunRow.started_at.desc()).limit(limit)
        if app is not None:
            query = query.where(EvalRunRow.app == app)
        with Session(self.engine) as session:
            return [_record(r) for r in session.scalars(query)]

    def metric_series(
        self, metric: str, *, app: str | None = None, limit: int = 20
    ) -> list[tuple[RunRecord, float]]:
        """The most recent ``limit`` values of a metric, oldest first."""
        query = (
            select(EvalRunRow, RunMetricRow.value)
            .join(RunMetricRow, RunMetricRow.run_id == EvalRunRow.run_id)
            .where(RunMetricRow.name == metric)
            .order_by(EvalRunRow.started_at.desc())
            .limit(limit)
        )
        if app is not None:
            query = query.where(EvalRunRow.app == app)
        with Session(self.engine) as session:
            rows = [(_record(run), value) for run, value in session.execute(query).tuples()]
        return list(reversed(rows))

    def load_runs(self, *, app: str) -> list[RunResult]:
        """Every stored run of an app, oldest first (input to drift detection)."""
        query = (
            select(EvalRunRow.result_json)
            .where(EvalRunRow.app == app)
            .order_by(EvalRunRow.started_at)
        )
        with Session(self.engine) as session:
            return [RunResult.model_validate_json(j) for j in session.scalars(query)]

    def count_runs(self) -> int:
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(EvalRunRow)) or 0
