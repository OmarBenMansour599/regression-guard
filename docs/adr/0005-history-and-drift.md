# ADR 0005: Run history database and drift detection

Status: Accepted (2026-11-18)

## Context
Phase 5 compares one run with one pinned baseline. That catches changes we make. It cannot catch drift: the provider changing the model behind the same name, or quality sliding slowly while our repository stays unchanged. That needs a history of comparable runs. The technical plan (section 6) proposed 11 tables plus a REST API in Phase 6.

## Decision
- **Files stay the source of truth for CI** (ADR 0002 unchanged). Every run also writes to a history database: local SQLite by default (`REGGUARD_DATABASE_URL`), PostgreSQL in deployment. A database failure while recording is a warning, never a failed run. `regguard history import` backfills old run files.
- **4 result tables instead of 11**: `eval_run` (headline columns plus the full run JSON, so the DB alone can rebuild any run), `run_metric`, `case_result` and `comparison`. Prompts, datasets and test cases already live, versioned and hashed, in git. Copying them into the DB would create a second source of truth. Baselines stay files.
- **Synchronous SQLAlchemy 2.0 + Alembic**, with migrations shipped inside the package and driven from Python (no launcher). Local SQLite is migrated automatically; other databases need an explicit `regguard db upgrade`. A spike confirmed everything works under Windows Smart App Control (ADR 0004).
- **Portable schema**: no PostgreSQL-only types (JSON stored as text). PostgreSQL is tested in CI with a service container, not installed locally.
- **Drift** (`comparison/drift.py`, pure):
  - Only *comparable* runs count: same app, prompt hash, dataset hash, case set and model as the baseline, and the same judge for judge scores.
  - Only *fresh* runs count: no cache hits.
  - DRIFT when the moving average over `window` runs is worse than the baseline by the warn threshold AND the last `consecutive` runs are all worse.
  - Fewer than `consecutive` runs is reported as "insufficient", never as OK.
  - `new_episode` marks the first drifting run, so alerts fire once per episode.
  - Only gating metrics decide the report status.
- **REST API moved** from Phase 6 to just before the dashboard (Phase 8), its only consumer.

## Consequences
+ History, trends and drift with no server; CI unchanged.
+ One source of truth for prompts and datasets (git); the DB holds results only.
+ Tests cover migrations on both SQLite and PostgreSQL.
- Drift needs scheduled fresh runs (`--cache refresh`), which cost API calls; automated in Phase 9.
- Results are stored twice (file + DB). Accepted: the file is the CI artifact, the DB is the query layer.
