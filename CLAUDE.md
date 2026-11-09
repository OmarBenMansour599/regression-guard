# RegressionGuard — engineering instructions

CI for LLM behavior: evaluate prompt/model changes against a versioned, human-labeled golden dataset, diff against an explicit baseline, gate deployments on significant regressions. Full design: `docs/technical-plan.md`. Decisions: `docs/adr/`.

## Working rules (non-negotiable)
1. Plan first: before each feature state what/why, the exact files to create/modify, and tests. Wait for approval.
2. Small vertical slices, one phase and one feature at a time. Never generate the whole app at once.
3. Tests alongside code. Run `ruff`, `mypy`, `pytest` and report real output. Never claim something works without running it; report failures plainly.
4. Typed, modular code. No unnecessary dependencies or abstractions.
5. Never hardcode or read secrets. Secrets only via env vars (`REGGUARD_*`); `.env` is off limits.
6. Major architectural changes need an ADR and user approval first.
7. Golden-dataset labels are human-written. Never generate ground truth with an LLM.
8. Keep docs and the Status section below current at the end of each task.

## Architecture rules
- Modular monolith. Layering: `api, cli -> services -> {evaluation, comparison, reporting, notifications, storage} -> {metrics, providers} -> core`.
- `core`, `metrics`, `comparison` do no I/O (pure, deterministic, easily tested).
- CLI is the primary interface; CI uses the CLI and must not need the API server.
- Baselines are explicit and pinned; file baselines in `baselines/` are changed only via the CLI.
- Infra errors are never reported as quality regressions (status `ERROR`).

## Commands (from `backend/`)
- `uv sync` · `uv run pytest` · `uv run ruff check .` · `uv run ruff format .` · `uv run mypy src`

## Environment
- Python 3.12 managed by uv (system Python 3.14 is NOT used). Windows + PowerShell dev machine; use `pathlib`, LF line endings.
- LLM access: OpenAI-compatible endpoints (OpenRouter, Groq; free tiers, strict rate limits -> low concurrency, cache, backoff).

## Status
- Decisions approved: modular monolith; file baselines in CI + DB for history; significance-aware gating; dashboard deferred until CLI/engine/CI are solid; private repo; OpenRouter/Groq as providers.
- Done: Phase 0 docs; Phase 1 foundation (pyproject, core config/errors/logging/types, CLI `--version`, 18 unit tests, import-linter contract, CI workflow, pre-commit, .env.example). Verified locally: ruff, ruff format, mypy strict, pytest, lint-imports all pass.
- Pending: first CI run on GitHub (not yet verified); install `gh` CLI (needed by Phase 9); `pre-commit install` (optional).
- Not started: Phase 2 (providers, prompts). Scaffold files for later phases are still empty.
- Next action: Phase 2 plan (OpenAI-compatible provider, prompt loader, mock provider).
- Known issues: on this Windows machine `uv run mypy` is blocked by an Application Control policy; use `uv run python -m mypy`. ci.yml runs on Linux and is unaffected.
