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
- All checks (same as CI): `uv run python scripts/check.py`
- Single tools: `uv run python -m pytest` · `uv run python -m ruff check .` · `uv run python -m ruff format .` · `uv run python -m mypy`
- CLI: `uv run python -m regguard ...` (the `regguard` launcher may be blocked; `python -m` always works)
- Always use `python -m <tool>`, never generated `.exe` launchers (Smart App Control, ADR 0004).

## Environment
- Local: signed system Python 3.14 (`C:\Python314`), `.python-version` = 3.14. Supported: `>=3.12`; CI tests 3.12 and 3.14.
- Windows 11 with Smart App Control ENFORCING: unsigned binaries (uv-managed Pythons, uv .exe launchers, some compiled wheels) are blocked. Never suggest disabling it. mypy is built from source for this reason.
- PowerShell dev machine; use `pathlib`, LF line endings.
- LLM access: OpenAI-compatible endpoints (OpenRouter, Groq; free tiers, strict rate limits -> low concurrency, cache, backoff).

## Status
- Decisions approved: modular monolith; file baselines in CI + DB for history; significance-aware gating; dashboard deferred until CLI/engine/CI are solid; private repo; OpenRouter/Groq as providers.
- Done: Phase 0 docs; Phase 1 foundation (pyproject, core config/errors/logging/types, CLI `--version`, 18 unit tests, import-linter contract, CI workflow, pre-commit, .env.example). Verified locally: ruff, ruff format, mypy strict, pytest, lint-imports all pass.
- Done: Phase 2 (OpenAI-compatible httpx provider, mock provider, factory; versioned prompt schema/loader/renderer/hash; AppSpec + support-email schema + registry; regguard.yaml loader; `invoke` service; CLI `prompt list|show`, `try`). 81 tests, 96% coverage; ruff, mypy strict, lint-imports (6-layer contract) pass. LiteLLM dropped.
- Models (2026-11-10, OpenRouter): classifier `google/gemma-4-26b-a4b-it:free`, judge `nvidia/nemotron-3.5-super-vl:free`. Free tier: 20 req/min, 50 req/day (<$10 credits) or 1000/day.
- Real-API smoke test passed 2026-11-10 (via override `nvidia/nemotron-3.5-super-vl:free`: valid output, 21 s, 132 completion tokens for ~25 visible -> hidden reasoning tokens). Gemma `:free` variants share Google AI Studio's upstream pool and returned 429; fix = BYOK Google key in OpenRouter (pending, user).
- Pending: CI on GitHub unverified; `gh` CLI (Phase 9).
- Carry into Phase 4: (1) record the *effective* model in run metadata, since `REGGUARD_LLM_MODEL` override leaves the prompt hash unchanged; (2) readable upstream error messages (OpenRouter `metadata.raw`); (3) disable or budget reasoning tokens for reasoning models (latency + cost).
- Done: Phase 3 tooling (2026-11-12): `datasets/` models (GoldenCase, manifest, content hash excl. notes), loader reporting all problems at once, lint (PII heuristics + quality), stratified selection; `services/datasets.py`; CLI `dataset list|validate [--strict]|stats`; `docs/labeling-guide.md`; YAML dataset template (cases.jsonl removed). 114 tests; all checks pass on 3.14. ADR 0004 (Python 3.14 local / Smart App Control).
- In progress (USER): writing golden cases, batch 1 = 12 cases (3/category) in `examples/support-email-classifier/datasets/emails/v1/cases.yaml`, then Claude reviews labels (review only, never author).
- Done: batch 1 (12 cases) committed and reviewed (labels correct; asked user to reduce `critical` to 2-3 and vary email form). Guide clarified (pre-sales pricing = general). Placeholder evaluate.yml removed (it caused red CI runs).
- Done: Phase 4 code (2026-11-12): metrics (Metric protocol, schema_valid, label_exact, aggregates incl. per-label slices, fresh-only latency p50/p95, tokens), evaluation (cache read-write/refresh/off, executor with semaphore + RPM limiter + full-jitter retries + Retry-After + abort on auth/5 consecutive failures, runner), storage/file_store (runs/<id>/result.json), services/run_service (prepare + budget guard + execute + git sha with -dirty), CLI `run`, `runs list|show`; RunMeta gained model_override, served_models, selection, n_samples, execution stats; readable OpenRouter upstream errors. 149 tests, 95% coverage, all checks pass (verified against committed dataset).
- First real run 2026-11-12 (24-case dataset, --limit 12): Gemma free pool 429 on every call -> retries -> abort after 5 consecutive failures -> status ERROR (correct behavior, 32 API calls burned). Fixes applied: 0-case selections refused; 429 backoff now equal-jitter 5s base/60s cap (was 1s full jitter); retry logs shortened. 151 tests pass. Real-run acceptance PASSED 2026-11-12 after user set up BYOK (Google AI Studio key in OpenRouter): run 1 ERROR (2x HTTP 504 upstream, 17% > 10%), run 2 COMPLETED (10 cached + 2 fresh, 12/12 correct, p50 ~1.5 s, ~410 tokens/case), run 3 COMPLETED with 0 API calls. Phase 4 DONE.
- Phase 5 notes: model summaries start "The customer is..." vs references "Customer..." -> summary metrics must be semantic, not lexical. 5xx (504) retries could use longer backoff too if they recur.
- Pending (USER, old): fix email-0019 (done by user) (`email:` has subject/body sub-keys; must be one text block); commit; real run `regguard run -p v1` on the 12 cases (acceptance), then rerun to confirm 0 API calls (cache). Gemma free pool 429s: BYOK still recommended.
- Done: Phase 5a code (2026-11-12): pure `comparison/` package (diff: majority-vote case outcomes, errored cases skipped, NEW/REMOVED; stats: exact one-sided McNemar, pure Python; verdict: per-metric warn/critical thresholds + evidence rule p<alpha OR >=min_regressed_cases, hard rules schema floor + critical cases, Verdict.ERROR for errored candidates, machine-readable reasons); `core/gating.py` (GateConfig, sign = bad direction, user entries merge over defaults); `storage/baseline_store.py`; `services/compare_service.py`; CLI `baseline promote|list|show`, `compare [--against] [--fail-on-warn] [--allow-dataset-change]`, `run --baseline`; exit 4 = gate FAIL. RunMeta gained `case_labels`, `critical_case_ids` (older runs: labels inferred from score detail). Binary metrics are compared on paired cases only; tokens compared per case. 221 tests, 96% coverage, all checks pass. Offline check on real runs: identical runs PASS; ERROR baseline refused.
- Pending (USER): Phase 5a real demo: `run -p v1 --limit 12` (cached) -> `baseline promote` -> `run -p v2 --limit 12 --baseline main` (~12 calls). Commit `examples/support-email-classifier/baselines/main.json`.
- Not started: Phase 5b (summary metrics: deterministic + semantic similarity + judge; precision/recall/F1; drift). slack.py scaffold still empty.
- Next action: user runs the 5a demo; then Phase 5b plan.
- Known issues: none open.
