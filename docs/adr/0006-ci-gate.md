# ADR 0006: The pull request gate and the daily monitor in GitHub Actions

Status: Accepted (2026-11-22)

## Context
Phases 5 to 7 built the verdict, the history and the reports, but a person had to type the commands. The goal of the project is "CI for LLM behaviour": a prompt change that makes quality worse must not reach `main`. Constraints:
- free LLM tier, about 50 calls per day;
- a private repository, where GitHub Free cannot enforce required checks;
- secrets must never reach untrusted code.

## Decision
- **`evaluate.yml`** runs on `pull_request` and `workflow_dispatch`. Its single job, `RegressionGuard gate`, is the required check.
- **All decisions live in tested Python** (`services/ci_service.py`, CLI `regguard ci plan | summarize | baseline-prompt`). The workflow only lists changed files, runs commands and posts the comment.
- **What runs.** Changed prompt files are evaluated, at most 3 per PR. A config- or baseline-only change re-evaluates the baseline's prompt. A dataset change without a new baseline blocks the PR. Every run uses exactly the baseline's cases (`run --cases-from-baseline`).
- **The judge is off in PR runs**, because it is non-gating and doubles the cost. It is available in manual runs.
- **Fail closed.** ERROR (provider outage, budget) fails the check, as FAIL does; the comment says to re-run. A fork PR that touches a prompt fails, because it has no secrets.
- **The check always reports.** A PR with nothing relevant gets a green check, never a skipped workflow, which would leave a required check pending forever.
- **One PR comment**, found again by a hidden marker and the bot's login, and edited on each push. Same content rules as Phase 7: no email text, no model answers.
- **Response cache** carried between runs with the Actions cache (`restore` + `save` with `always()`, so a failed gate still saves the answers it paid for).
- **`monitor.yml`**, daily: fresh run of the baseline prompt, recorded in the history database, then `drift --fail-on-drift --notify`. The SQLite history database is carried in the Actions cache. Losing it resets drift to INSUFFICIENT, which is safe.
- **Supply chain.** Actions are pinned to commit SHAs on Node 24 versions (`ci.yml` updated too). Token permissions are minimal: `contents: read`, plus `pull-requests: write` on the gate job only. Values from the PR reach the shell only through environment variables.
- **Merge enforcement** through a ruleset, which GitHub Free offers on public repositories only. **The repository becomes public** (decided 2026-11-22; paid plan not an option). Checked before switching: no secret and no `.env` anywhere in the git history, no database or run files tracked, no personal-data warnings in the golden dataset. Fork workflows need approval before they run; fork PRs that touch prompts fail closed (above).

## Consequences
+ A prompt regression cannot reach `main` once the ruleset is active.
+ The PR shows why, with the exact cases and a link to the HTML report.
+ A provider outage blocks merging until a re-run: safe but occasionally annoying. Re-runs reuse cached answers.
- Each prompt-changing PR costs about 12 calls; heavy PR days can exhaust the free quota (the cap is per run, the quota per day).
- The Actions cache is best-effort storage for history: a long pause in monitoring loses it.
- Fork PRs touching prompts need a maintainer's manual run.
- Public repository: the code, the golden dataset, the baselines and every commit's author email are visible to anyone. A secret committed by mistake must be revoked, not just deleted. Scheduled workflows pause after 60 days without commits.
