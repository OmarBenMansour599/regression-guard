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
- Done: Phase 2 (OpenAI-compatible httpx provider, mock provider, factory; versioned prompt schema/loader/renderer/hash; AppSpec + support-email schema + registry; regguard.yaml loader; `invoke` service; CLI `prompt list|show`, `try`). 81 tests, 96% coverage; ruff, mypy strict, lint-imports (6-layer contract) pass. LiteLLM dropped.
- Models (2026-11-10, OpenRouter): classifier `google/gemma-4-26b-a4b-it:free`, judge `nvidia/nemotron-3.5-super-vl:free`. Free tier: 20 req/min, 50 req/day (<$10 credits) or 1000/day.
- Real-API smoke test passed 2026-11-10 (via override `nvidia/nemotron-3.5-super-vl:free`: valid output, 21 s, 132 completion tokens for ~25 visible -> hidden reasoning tokens). Gemma `:free` variants share Google AI Studio's upstream pool and returned 429; fix = BYOK Google key in OpenRouter (pending, user).
- Pending: CI on GitHub unverified; `gh` CLI (Phase 9).
- Carry into Phase 4: (1) record the *effective* model in run metadata, since `REGGUARD_LLM_MODEL` override leaves the prompt hash unchanged; (2) readable upstream error messages (OpenRouter `metadata.raw`); (3) disable or budget reasoning tokens for reasoning models (latency + cost).
- Not started: Phase 3 (golden dataset). Scaffold files executor.py, runner.py, slack.py are still empty.
- Next action: Phase 3 plan (dataset schema/loader/hash, PII lint, labeling guide).
- Known issues: on this Windows machine `uv run mypy` is blocked by an Application Control policy; use `uv run python -m mypy`. ci.yml runs on Linux and is unaffected.
