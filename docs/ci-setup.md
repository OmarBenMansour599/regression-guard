# CI gate setup (about 15 minutes, no coding)

RegressionGuard runs in GitHub Actions with two workflows:

| Workflow | When | What it does |
|---|---|---|
| `evaluate.yml` (check **RegressionGuard gate**) | every pull request, or by hand | Finds which prompt versions the PR changes, evaluates them on the real LLM against baseline `main`, posts one PR comment (updated on every push) and fails the check on FAIL or ERROR. |
| `monitor.yml` | every day at 06:17 UTC, or by hand | Re-runs the baseline's prompt with fresh calls, records it in the history database and checks drift. Sends Slack alerts if Slack is configured. |

Screens on github.com change from time to time; a label may differ slightly, the steps do not.

## 1. Make merge blocking possible (public repository)

GitHub Free enforces required checks only on **public** repositories (private ones need a paid plan). This project is public for that reason. Before switching, and whenever you add files:

- **No secrets in the history.** `.env` is git-ignored and was never committed; keys live only in `.env` and in GitHub secrets. If a key ever lands in a commit, revoke it at the provider at once: deleting the commit is not enough once it is public.
- **No real personal data.** The golden emails are written by hand and checked by `regguard dataset validate` (personal-data warnings). Run outputs (`runs/`) and the database are git-ignored.
- **Your commit email is public.** Every commit shows its author's email address. To hide it in future commits: GitHub **Settings → Emails → Keep my email addresses private**, then `git config user.email <the ...@users.noreply.github.com address shown there>`. Past commits keep the old address; changing them means rewriting the history, which is a separate decision.

Then: repository **Settings → General → Danger Zone → Change visibility → Make public**.

Also set **Settings → Actions → General → Approval for running fork pull request workflows from contributors → Require approval for all external contributors**, so nobody's code runs in your Actions without you looking at it first.

## 2. Add the API key as a secret

1. On the repository page: **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `REGGUARD_LLM_API_KEY`. Value: your OpenRouter key (the same as in `.env`). **Add secret**.
3. Optional, for Slack alerts from the daily monitor: a second secret `REGGUARD_SLACK_WEBHOOK_URL` with the webhook URL (see `docs/slack-setup.md`).

Secrets are never shown again, never printed in logs (GitHub masks them), and never given to pull requests from forks.

## 3. Run the gate once

Push the workflows, then open **Actions → RegressionGuard gate → Run workflow**, prompt `v1`. It should end green (`GATE: PASS`): v1 compared with its own baseline. This first run also makes the check name known to GitHub, which step 4 needs.

## 4. Require the check before merging

1. **Settings → Rules → Rulesets → New ruleset → New branch ruleset**.
2. Name: `protect main`. Enforcement status: **Active**.
3. Target branches: **Add target → Include default branch**.
4. Tick **Require a pull request before merging** (0 approvals is fine when you work alone).
5. Tick **Require status checks to pass**, then **Add checks** and add:
   - `RegressionGuard gate`
   - `backend (3.12)`, `backend (3.14)` and `postgres` (the code checks)
6. Tick **Block force pushes**. Leave the bypass list empty. **Create**.

From now on, changes reach `main` only through a pull request with green checks.

## 5. Working with the gate

**What the PR comment says.** One table row per evaluated prompt, then the same summary as `regguard report` (verdict, reasons, metrics, changed cases). It never contains email text or model answers. The full HTML reports are in the workflow run's **Artifacts** (`regressionguard-reports`), linked from the comment.

| Verdict | Check | What to do |
|---|---|---|
| ✅ PASS / ⚠️ WARN | green | Merge (read the WARN reasons first). |
| ❌ FAIL | red | The change made quality worse. Fix the prompt and push again. |
| 🛑 ERROR | red | No verdict: the provider failed or the budget ran out. **Re-run failed jobs**: answers already received come from the cache, so a re-run costs only the missing calls. |
| Nothing to evaluate | green | The PR touches no prompt, dataset, baseline or `regguard.yaml`. |

**What is evaluated.**
- Each changed or added prompt file in `prompts/classify/` (at most 3 per PR, to fit the daily quota).
- If only `regguard.yaml` or the baseline changed: the baseline's own prompt, to check the new configuration.
- Engine code changes are covered by the unit tests in `ci.yml`, not by real LLM calls.
- The judge is off in PR runs (it is non-gating and doubles the cost). To include it, use **Run workflow** with **judge** ticked.

**Changing the golden dataset.** Old and new answer keys cannot be compared, so a PR that changes the dataset without a new baseline is blocked. In the same PR:

```powershell
uv run python -m regguard run -p v1 --limit 12 -c ../examples/support-email-classifier/regguard.yaml
uv run python -m regguard baseline promote <run_id> --replace --note "dataset v1 batch 3" -c ../examples/support-email-classifier/regguard.yaml
git add ../examples/support-email-classifier/baselines/main.json
```

The comment then warns reviewers that the baseline moved, and they can read the change in the PR diff.

**Evaluating a prompt by hand.** **Actions → RegressionGuard gate → Run workflow**, enter the prompt version.

## 6. Cost

The free tier allows about 50 API calls per day (shared with your local runs).

| What | API calls |
|---|---|
| A PR changing one prompt (12 cases, no judge) | about 12, capped at 30 including retries |
| Pushing again without changing the prompt | 0 (cached) |
| Daily monitor (fresh calls) | about 12, capped at 30 |
| Run by hand with the judge | about 24, capped at 50 |

## 7. Daily monitor

- It needs a few days of fresh runs before drift can say anything (`INSUFFICIENT` until 3 comparable runs exist).
- A red monitor run means the fresh run failed the gate or errored, or quality is drifting. The run summary and the `regressionguard-monitor` artifact have the details.
- The history database lives in the Actions cache. GitHub deletes caches unused for 7 days; the daily run keeps it alive. If it is lost, drift goes back to `INSUFFICIENT`, never to a false "OK".
- In a public repository, GitHub pauses scheduled workflows after 60 days without any commit. It emails you first; **Actions → RegressionGuard monitor → Enable workflow** restarts it.

## Security notes

- The workflows use `pull_request`, never `pull_request_target`.
- Pull requests from forks get no secrets: one that touches a prompt cannot be evaluated, so its check fails ("fail closed"). To evaluate it, first read its changes, then copy its branch into this repository and run the gate there by hand:
  `gh pr checkout <number>; git push origin HEAD:review/pr-<number>`, then **Run workflow** on branch `review/pr-<number>`.
- Third-party actions are pinned to exact commits.
- The PR comment is posted with the workflow's own short-lived token, which can only write comments.
