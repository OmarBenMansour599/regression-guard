"""Run history: eval_run, run_metric, case_result, comparison.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_run",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("app", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("prompt_hash", sa.String(80), nullable=False),
        sa.Column("dataset_version", sa.String(100), nullable=False),
        sa.Column("dataset_hash", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("judge_hash", sa.String(80), nullable=True),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("git_sha", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("n_cases", sa.Integer(), nullable=False),
        sa.Column("api_calls", sa.Integer(), nullable=False),
        sa.Column("cache_hits", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_eval_run_app_started", "eval_run", ["app", "started_at"])

    op.create_table(
        "run_metric",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("eval_run.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.UniqueConstraint("run_id", "name", name="uq_run_metric_run_name"),
    )
    op.create_index("ix_run_metric_name_run", "run_metric", ["name", "run_id"])

    op.create_table(
        "case_result",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("eval_run.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(100), nullable=False),
        sa.Column("sample_idx", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(50), nullable=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("judge_score", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "run_id", "case_id", "sample_idx", name="uq_case_result_run_case_sample"
        ),
    )
    op.create_index("ix_case_result_case", "case_result", ["case_id"])

    op.create_table(
        "comparison",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "candidate_run_id",
            sa.String(64),
            sa.ForeignKey("eval_run.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("baseline_run_id", sa.String(64), nullable=False),
        sa.Column("baseline_name", sa.String(64), nullable=True),
        sa.Column("verdict", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comparison_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "candidate_run_id", "baseline_run_id", name="uq_comparison_candidate_baseline"
        ),
    )


def downgrade() -> None:
    op.drop_table("comparison")
    op.drop_index("ix_case_result_case", table_name="case_result")
    op.drop_table("case_result")
    op.drop_index("ix_run_metric_name_run", table_name="run_metric")
    op.drop_table("run_metric")
    op.drop_index("ix_eval_run_app_started", table_name="eval_run")
    op.drop_table("eval_run")
