# ADR 0002: File baselines for CI, database for history

Status: Accepted (2026-11-09)

## Context
GitHub Actions runners are ephemeral, so a local SQLite file cannot provide a baseline across CI runs. The dashboard and drift detection need queryable history.

## Decision
- A baseline is an explicit, immutable result snapshot committed under `baselines/<app>/<name>.json` and promoted only via `regguard baseline promote`. CI compares against it with no server.
- The database (SQLite locally, PostgreSQL in deployment) stores full run history for the dashboard and drift. Its models serialize to the same Pydantic types as the file format.
- Comparisons check dataset content hashes and warn/refuse on mismatch.

Amendment (2026-11-12, Phase 5a, approved): baselines live next to each app's config, at `<baselines_dir>/<name>.json` (default `examples/<app>/baselines/`, set by `baselines_dir` in `regguard.yaml`), so each app is self-contained. A baseline file holds a header (name, source run id, promoted_at, git sha, note) plus the full `RunResult`. Overwriting needs `--replace`. Claude Code is denied direct edits to these files (`.claude/settings.json`).

## Consequences
+ Baseline changes are reviewable in PRs; CI is self-contained.
- Two storage paths to keep consistent; a single set of Pydantic types is the source of truth.
