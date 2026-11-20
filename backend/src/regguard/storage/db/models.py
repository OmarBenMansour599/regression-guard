"""History tables. Portable on purpose: no PostgreSQL-only types (JSON is stored as text).

Changing these models requires a new Alembic migration in ``migrations/versions``; a test
checks that the migrations and these models describe the same schema.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EvalRunRow(Base):
    """One evaluation run. ``result_json`` is the full RunResult: the DB alone can rebuild it."""

    __tablename__ = "eval_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100))
    prompt_hash: Mapped[str] = mapped_column(String(80))
    dataset_version: Mapped[str] = mapped_column(String(100))
    dataset_hash: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200))
    judge_hash: Mapped[str | None] = mapped_column(String(80))
    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    git_sha: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    n_cases: Mapped[int] = mapped_column(Integer)
    api_calls: Mapped[int] = mapped_column(Integer)
    cache_hits: Mapped[int] = mapped_column(Integer)
    result_json: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_eval_run_app_started", "app", "started_at"),)


class RunMetricRow(Base):
    """One aggregate per run and metric (including slices such as ``label_exact/billing``)."""

    __tablename__ = "run_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("eval_run.run_id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    value: Mapped[float] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("run_id", "name", name="uq_run_metric_run_name"),
        Index("ix_run_metric_name_run", "name", "run_id"),
    )


class CaseResultRow(Base):
    """One case x sample of a run: enough to find flaky cases without parsing run JSON."""

    __tablename__ = "case_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("eval_run.run_id", ondelete="CASCADE")
    )
    case_id: Mapped[str] = mapped_column(String(100))
    sample_idx: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    error_type: Mapped[str | None] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(String(100))
    judge_score: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("run_id", "case_id", "sample_idx", name="uq_case_result_run_case_sample"),
        Index("ix_case_result_case", "case_id"),
    )


class ComparisonRow(Base):
    """A candidate run compared with a baseline. Re-comparing the same pair replaces the row."""

    __tablename__ = "comparison"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("eval_run.run_id", ondelete="CASCADE")
    )
    baseline_run_id: Mapped[str] = mapped_column(String(64))  # baseline may not be in the DB
    baseline_name: Mapped[str | None] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comparison_json: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "candidate_run_id", "baseline_run_id", name="uq_comparison_candidate_baseline"
        ),
    )
