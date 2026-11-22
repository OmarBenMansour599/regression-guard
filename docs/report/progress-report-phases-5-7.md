# RegressionGuard: Progress Report (Phases 5 to 7)

**Project:** Model Regression Detection System ("RegressionGuard")
**Author:** Omar Ben Mansour
**Period covered:** 12 to 20 November 2026
**Status:** Phases 5 to 7 complete (comparison and regression detection, AI judge, run history
and drift detection, reports and Slack notifications). Next: Phase 9 (automatic gate in GitHub),
then Phase 8 (web API and dashboard).
**Previous report:** `docs/report/progress-report.md` (Phases 0 to 4).

---

## Contents

1. The project in one page
2. Key words explained (new in these phases)
3. How the system works now (big picture)
4. Technology choices and why
5. What was built, phase by phase
6. Every new or changed file explained
7. Real results obtained
8. Difficulties met and how they were solved
9. Important design decisions
10. Quality: how we know it works
11. What remains to do
12. How to run it
13. Appendix: commit history

---

## 1. The project in one page

### Reminder: the problem and the solution

An LLM application is controlled by a **prompt** and a **choice of model**. Changing either
can silently make the application worse. RegressionGuard is an **automated testing system for
LLM behaviour**: it runs the application on a human-checked answer key (the *golden dataset*),
scores the answers, compares them with a trusted earlier version (the *baseline*), and raises
an alarm when quality drops.

The example application is still the **customer-support email classifier**: it reads a
customer email and returns a **category** (`billing`, `technical`, `account`, `general`) and a
**one-sentence summary**.

### Where we were at the end of Phase 4

The system could **run** an evaluation: call the AI reliably, score every answer, and save a
complete, traceable result file. It could not yet say whether a new version was **better or
worse** than before. That was the missing heart of the project.

### What Phases 5 to 7 added

| Phase | Question it answers | In one sentence |
|---|---|---|
| **5a** | "Did my change make things worse?" | Compares a new run with a pinned baseline, case by case, and gives a verdict: PASS, WARN, FAIL or ERROR. It only fails a change when the drop is both large and unlikely to be chance. |
| **5b** | "Are the summaries still good?" | Adds summary checks: a format rule, a word-overlap score, and a second AI acting as a **judge** that grades each summary from 1 to 5. Also adds precision, recall and F1 per category. |
| **6** | "Is quality slowly sliding when nobody changed anything?" | Records every run in a **history database** and detects **drift**: a slow, repeated decline over many runs of the same prompt and model. |
| **7** | "How does the team find out?" | Produces a readable **HTML report**, a short **Markdown summary** (ready for a GitHub comment), and a **Slack message** when something goes wrong. |

### Where we are now

> The complete regression-detection loop works on the command line, and it has been verified
> on the real AI. When the deliberately weak prompt `v2` is compared with the trusted `v1`,
> RegressionGuard answers **FAIL**. It names the 4 emails that broke and explains why: the
> model wrapped its answer in an extra pair of brackets, so the program reading it could not
> use it. It writes a report anyone can open, and it can post the alert to Slack.

What is still missing is **automation**: today a person types the commands. Phase 9 will make
GitHub run them on every pull request that changes a prompt and block the merge on FAIL.

---

## 2. Key words explained (new in these phases)

The words from the first report (LLM, prompt, token, golden dataset, baseline, cache, CI...)
are not repeated here.

| Term | Simple meaning |
|---|---|
| **Comparison** | Putting a new run (the *candidate*) next to the baseline, case by case and metric by metric. |
| **Candidate** | The new run being judged (for example, prompt `v2`). |
| **Promote (a baseline)** | Declaring a run "the trusted reference". Done on purpose, with a command, never automatically. |
| **Verdict** | The final answer of a comparison: **PASS** (no problem), **WARN** (a drop worth a look), **FAIL** (a real regression: block the change), **ERROR** (the run itself failed for technical reasons, so no quality judgment is possible). |
| **Exit code** | The number a command returns when it finishes. Automated systems such as GitHub read it: 0 = fine, 4 = gate failed. |
| **Gate** | The set of rules that turns measurements into a verdict ("quality gate"). |
| **Threshold** | How big a drop must be before it matters, for example "warn at −3 points, fail at −8 points". |
| **Paired comparison** | Comparing the *same* test case in both runs, instead of only comparing two averages. It shows exactly which cases changed. |
| **Regressed / improved case** | A case that passed in the baseline and fails now (regressed), or the opposite (improved). |
| **Statistical significance, p-value** | A way to measure how likely a difference is to be pure chance. A small p-value (here below 0.10) means "very unlikely to be random". |
| **McNemar test / sign test** | The specific statistical test used: it only looks at cases that changed, and asks whether "more broke than got fixed" could be luck. |
| **Hard rule** | A rule that fails the gate regardless of statistics, for example "a case marked critical must never regress". |
| **Precision / recall / F1** | Recall: of the emails that *are* billing, how many were labelled billing. Precision: of the emails *labelled* billing, how many really are. F1 combines both. **Macro F1** is the average F1 over the 4 categories. |
| **LLM judge** | A second AI model used to grade the answers of the first one (here: grading summaries from 1 to 5), following a written grading rubric. |
| **Rubric** | The written grading instructions given to the judge (what a 5 looks like, what a 2 looks like). |
| **Calibration** | Checking that the judge's grades agree with a human's grades before trusting it. |
| **Gating / non-gating metric** | A gating metric can fail the gate. A non-gating (informational) metric is shown but never blocks a change. |
| **Drift** | Quality slowly getting worse over time *without any change on our side*, for example because the provider quietly updated the model behind the same name. |
| **Moving average** | The average of the last N values (here the last 7 runs), which smooths out day-to-day noise. |
| **Drift episode** | The period during which a metric keeps drifting. An alert is sent once, when the episode starts, not every day. |
| **Database, SQLite, PostgreSQL** | A database stores data in tables that can be searched. SQLite is a database in a single local file (no server). PostgreSQL is a full database server, used in deployment. |
| **Migration** | A versioned script that creates or changes database tables, so every database can be upgraded safely to the latest structure. |
| **Webhook (Slack incoming webhook)** | A secret web address that lets a program post messages into one Slack channel, and nothing else. |
| **Escaping** | Neutralising special characters in text so they are shown as text, not interpreted (for example, preventing a name from triggering `@channel` in Slack, or HTML code from running in a report). |
| **Golden file** | In testing: a saved "expected output" file. The test fails if the produced output differs from it. |

---

## 3. How the system works now (big picture)

### 3.1 The full flow of a checked change

When a developer types `regguard run -p v2 --baseline main --report --notify`:

1. **Run the evaluation** exactly as in Phase 4: load the configuration, the prompt and the
   golden dataset, call the AI for each case (with the rate limits, retries, cache and budget),
   and score each answer. **New:** the summary is also checked (format and overlap), and an AI
   judge grades it from 1 to 5.
2. **Enforce a hard cost cap** during the run: the number of real API calls, retries included,
   can never exceed `--max-requests` (new after an incident, section 8).
3. **Save the run** to `runs/<run-id>/result.json`, as before.
4. **Record the run in the history database** (new in Phase 6). If the database is unavailable,
   this is only a warning: the run itself is never lost or failed because of it.
5. **Load the baseline** `main` from `baselines/main.json` (a file kept in git).
6. **Compare** the candidate with the baseline (Phase 5):
   - pair the cases that exist in both runs and see which ones regressed or improved;
   - for each metric, compute the change and compare it with the warn and critical thresholds;
   - check the evidence: is the drop statistically significant, or did enough cases break?
   - apply the hard rules (minimum format validity, critical cases);
   - decide the verdict: PASS, WARN, FAIL or ERROR, with a list of machine-readable reasons.
7. **Save and record the comparison** (file next to the run, and in the database).
8. **Write the reports** (Phase 7): an HTML page and a Markdown summary in `reports/`.
9. **Notify Slack** (Phase 7) if the verdict is one of the configured events (by default FAIL
   and ERROR). PASS never sends a message.
10. **Exit** with the verdict's code: 0 for PASS/WARN, 4 for FAIL, 3 for ERROR. The report
    and Slack steps run *before* the exit and never change the code.

A separate command, `regguard drift`, looks at the history of comparable runs (same prompt,
model and dataset) and reports whether quality is sliding over time.

### 3.2 How the code is organised now

The same layered "modular monolith" as before, with new layers. Each layer may only use the
layers below it. The rule is still checked automatically on every change.

```
  cli            what the user types (commands)
  services       the "use cases": run, compare, history, drift, report, notify
  evaluation | comparison | reporting | notifications
                 running cases | verdicts and drift | HTML/Markdown | Slack
  metrics        scoring answers (now also summaries, judge scores, F1)
  apps           the application under test (email classifier)
  prompts | datasets | storage
                 prompt files, golden data, run files, baselines, history database
  providers      talking to the AI service
  core           shared building blocks (types, settings, gate rules, errors, logging)
```

New since the last report: `comparison` (pure calculations, no files or network),
`reporting` (pure: turns results into text), `notifications` (Slack), and the `storage/db`
package (database). The rule "`core`, `metrics` and `comparison` do no input/output" keeps the
decision logic fully reproducible and easy to test.

---

## 4. Technology choices and why

Only the additions since the last report are listed.

| Need | Choice | Why this one |
|---|---|---|
| Statistics (significance test) | **Plain Python** (exact binomial calculation) | The test needed is about 30 lines of code. Adding SciPy for it would be a heavy dependency, and on this Windows machine compiled packages can be blocked by Smart App Control. |
| Summary similarity | **Word-overlap score written in Python**, not "embeddings" | Embedding models need PyTorch, a very large install that Smart App Control may block. The overlap score is kept as information only; the AI judge does the real grading. |
| Judge model | **NVIDIA Nemotron 3.5 Super** (free on OpenRouter), with low "reasoning effort" | A different family from the classifier (Gemma), so the model is not grading itself. Low reasoning effort keeps answers fast and cheap. |
| Database access | **SQLAlchemy 2.0** (synchronous) | The standard Python database library. Synchronous because the command-line tool does not need async complexity. |
| Database migrations | **Alembic**, driven from Python | The standard tool for SQLAlchemy. Driven from code, because its command launcher could be blocked by Smart App Control. |
| Local database | **SQLite** (built into Python) | Zero installation, one file. |
| Deployment database | **PostgreSQL** (tested in GitHub CI only) | Robust and standard. Tested automatically in CI with a temporary database server, so nothing has to be installed locally. Installed only with the optional `postgres` extra. |
| HTML report | **Jinja2** templates | The standard Python template engine. Automatic escaping protects against code hidden in emails or model answers. |
| Charts in the report | **Inline SVG** generated in Python | Small trend lines with no JavaScript and no chart library: the report is one self-contained file. |
| Notifications | **Slack incoming webhook**, sent with httpx (already used) | No Slack library needed, minimal permissions (can only post into one channel). |

Deliberately **not** added: SciPy, NumPy, PyTorch or sentence-transformers (see above), a
Slack SDK, a JavaScript chart library, a task queue or a scheduler. The web API that the plan
placed in Phase 6 was moved to Phase 8, just before the dashboard, which is its only user
(ADR 0005).

---

## 5. What was built, phase by phase

### Phase 5a: Comparison and the regression gate

**Goal:** answer "is the new version worse than the baseline?" with a verdict that can block a
deployment, without false alarms on a small dataset.

**What we built:**

- **Baselines as files** (`baselines/main.json`, next to the application's configuration).
  A baseline is a run that a person *promotes* with `regguard baseline promote <run> --name main`.
  It records who promoted it, when, and which run it came from. Baselines are never changed
  automatically, and the AI assistant is even forbidden by its permissions to edit them.
- **Case-by-case comparison** (`comparison/diff.py`): for every case present in both runs, was
  it passing before and now? Cases are labelled *regressed*, *improved*, *unchanged*, *new* or
  *removed*. Cases that failed for technical reasons are left out, never counted as regressions.
  If a case was sampled several times, a majority vote decides its outcome.
- **Thresholds per metric** (`core/gating.py`). Each metric has a "warn" and a "critical"
  threshold, and the sign says which direction is bad. For example `label_exact` (accuracy)
  warns at −3 points and is critical at −8 points; `tokens_per_case` warns at +20% and is
  critical at +50%. The project's `regguard.yaml` can override any of them.
- **Evidence before alarm** (`comparison/stats.py`, ADR 0003). A drop beyond a threshold only
  counts if it is *also* backed by evidence: either the McNemar test says it is unlikely to be
  chance (p below 0.10), or at least 3 cases regressed. This avoids failing a change because
  one or two answers randomly flipped.
- **Hard rules** that fail the gate whatever the statistics say: format validity
  (`schema_valid`) below 95%, or any case marked `critical` that regressed.
- **The verdict** (`comparison/verdict.py`): PASS, WARN, FAIL, or the new **ERROR** when the
  candidate run itself failed technically. Every verdict comes with machine-readable *reasons*
  (for example `critical_regression`, `schema_valid_floor`), plus information notes such as
  `statistical_power`: "with 12 cases, one case is 8.3 points; at least 4 one-way regressions
  are needed for significance".
- **Safety checks:** comparing runs made on different dataset versions is refused unless
  `--allow-dataset-change` is given; a baseline that is itself in ERROR is refused.
- **Commands:** `baseline promote | list | show`, `compare <run> [--against <run>]`,
  `run ... --baseline main`, with `--fail-on-warn` for strict pipelines. A FAIL returns
  **exit code 4**, which is what GitHub will use in Phase 9 to block a merge.

**Result:** 221 tests passing. Real demo: `v2` compared with `v1` gives **FAIL** (section 7).

### Phase 5b, part 1: Summary metrics and per-category scores (offline)

**Goal:** measure the second half of the answer (the summary), and give a fuller picture of
classification quality. No AI involved yet.

**What we built:**

- **"Not applicable" scores.** If an answer is not valid JSON, we cannot read its category, so
  `label_exact` now returns "not applicable" instead of "wrong". The format failure is counted
  once, by `schema_valid`, instead of twice.
- **`summary_format`** (gating): the summary must be one sentence, 5 to 40 words, and not
  copied from the email.
- **`summary_similarity`** (information only): how many important words the summary shares
  with the human reference summary, ignoring the usual opening "The customer...".
- **Precision, recall, F1 per category and macro F1** (`metrics/classification.py`).
- **Comparison of scores that are not pass/fail** (for example a similarity of 0.62 versus
  0.58): each case is paired, small differences below a tolerance ("epsilon") are ignored, and
  the same sign test decides whether the drop is significant.
- **Longer waits for server errors** (HTTP 5xx), after the Phase 5a demo showed 8 retries that
  came too fast.

**Result:** 248 tests passing. Real check with 0 API calls (everything from cache): verdict
unchanged, and `summary_similarity` stayed around 0.5 even on good summaries. This confirmed
that word overlap is a weak signal, and that an AI judge was needed.

### Phase 5b, part 2: The AI judge

**Goal:** grade each summary the way a careful human would, without letting an unreliable
grader block deployments.

**What we built:**

- **A versioned judge prompt** (`prompts/judge/v1.yaml`, then `v2.yaml`): a 1 to 5 rubric,
  worked examples, and clear markers around the email and summary, so instructions hidden in an
  email are treated as data, not obeyed. The judge model and its settings live in this file,
  like the classifier's.
- **Strict reading of the judge's answer**: it must be `{"score": 1-5, "reason": "..."}`.
  An unreadable judge answer is recorded as a *judge error*, never as a low score, so a broken
  judge cannot make the application look worse.
- **A separate executor for the judge** that shares the same rate limiter and budget as the
  classifier, so the two together never exceed the provider's limits.
- **Full traceability:** each result records which judge model and judge prompt version
  produced the grades. If baseline and candidate were graded by *different* judges, the
  comparison skips the judge score (reason `judge_changed`), because the grades are not
  comparable.
- **Non-gating by default:** `summary_judge` is shown in every comparison but cannot fail the
  gate until the judge has been calibrated on deliberately bad summaries.
- **Commands:** `run --judge / --no-judge`; `runs show` prints the summary and the judge's
  reason for every score of 3 or less.

**Judge improvement (follow-ups 1 and 2, chosen by you):** the first real test showed two
issues: the judge gave 5/5 to a summary containing a customer's full name (personal data), and
penalised a summary for leaving out a compliment. **Judge prompt v2** caps the score at 3 when
personal data appears and states that greetings and compliments are not required details.
After this, the judge agreed with a human reading on **12 of 12** cases.

**Result:** 280 tests passing. Phase 5 done.

### Phase 6: Run history and drift detection

**Goal:** remember every run, show trends, and detect slow quality decline that no code change
explains (ADR 0005).

**What we built:**

- **A history database** (`storage/db/`): 4 tables. `eval_run` stores one row per run,
  including the complete result, so the database alone can rebuild any run. `run_metric` has
  one row per metric per run, for fast trends. `case_result` has one row per case per run.
  `comparison` stores the verdicts. Prompts and datasets are *not* copied into the database:
  git already versions them, and a second copy would risk disagreeing with it.
- **SQLite by default** (`.regguard/regguard.db`, created and upgraded automatically),
  **PostgreSQL in deployment**. A new GitHub Actions job starts a temporary PostgreSQL 16
  server and runs the database tests against it.
- **Migrations shipped inside the package** and run from Python, so `regguard db upgrade`
  works without the Alembic launcher.
- **Automatic recording:** `run` and `compare` write to the database. Any database problem
  becomes a yellow warning; the run and its verdict are unaffected.
- **Importing older runs:** `regguard history import` loads all existing run and comparison
  files (0 API calls).
- **Drift detection** (`comparison/drift.py`, pure logic):
  - only **comparable** runs count: same app, prompt fingerprint, dataset fingerprint, case
    set and model (and the same judge for judge scores);
  - only **fresh** runs count (no cached answers), since a cached answer cannot drift;
  - a metric is in **DRIFT** when the average of the last 7 runs is worse than the baseline by
    the warn threshold **and** the last 3 runs are all worse;
  - with fewer than 3 comparable runs, the answer is **INSUFFICIENT**, never a falsely
    reassuring OK;
  - the first drifting run is marked as a **new episode**, so an alert is sent once;
  - only gating metrics decide the overall status (an informational metric cannot fail a
    scheduled job).
- **Commands:** `history list | import | trend --metric <name>`, `drift [--fail-on-drift]`,
  `db upgrade`.

**Result:** 320 tests passing (plus 6 PostgreSQL tests that run in CI only).

**Cost-control fix after the first monitoring run (20 November).** The provider was
overloaded. 12 planned calls became **36 real calls**, because retries were not counted in the
budget. `--max-requests` is now a **hard cap on real API calls, retries included**, shared by
the classifier and the judge. If it is reached, the run stops cleanly with status ERROR and
the message "API call budget exhausted". Every run now prints a `Budget:` line.
324 tests passing.

### Phase 7: Reports and Slack notifications

**Goal:** make each verdict readable by people who will never open a terminal, and alert the
team when something goes wrong.

**What we built:**

- **HTML report** (`reporting/html.py` + template), one self-contained file per run in
  `reports/<run-id>.html`. It shows:
  - a large verdict banner and the main reasons;
  - provenance: app, prompt version and fingerprint, model, dataset, baseline, judge, code
    version, cost;
  - the metrics table, with small **trend lines** drawn from the history database;
  - the **changed cases side by side**: the email, the expected answer, the baseline's answer
    and the candidate's answer;
  - the other failing cases, then all cases in a folded section.

  It adapts to light and dark mode, contains **no JavaScript**, and every piece of text coming
  from an email or the model is escaped, so a malicious email cannot inject code into the
  report.
- **Markdown summary** (`reporting/markdown.py`), `reports/<run-id>.md`: verdict, reasons,
  metrics table and up to 10 changed cases. It is designed to be posted as a GitHub pull
  request comment in Phase 9. It **never contains email text or model answers**, because PR
  comments are widely visible and real emails contain personal data.
- **Slack notifications** (`notifications/slack.py`): formatted messages for a failed
  comparison, a run in ERROR, the start of a drift episode, and a connection test. They contain
  the verdict, app, prompt, model, reasons, ids of regressed cases and the report path, but
  never email text or model answers.
- **Safety of the Slack integration:**
  - notifications are **opt-in**: only sent with `--notify`, and only for the events listed in
    `regguard.yaml` (default: fail, error, drift; warn can be added);
  - the webhook address is a secret, read only from the environment (`.env` locally, a GitHub
    secret in CI). It is never printed, even in error messages, and only `https://` addresses
    are accepted;
  - all text is escaped so that a name like `<!channel>` cannot notify the whole channel;
  - a Slack failure is reported as a warning and **never changes the verdict or the exit code**.
- **Commands:** `report <run-id>` (works on any stored run, 0 API calls), `--report` and
  `--notify` on `run` and `compare`, `--notify` on `drift`, and `notify test`.
- **Documentation:** `docs/slack-setup.md`, a 10-minute, no-coding guide to create the Slack
  webhook and store it safely.

**Result:** 353 tests passing, 96% of the code exercised by tests. A real report was generated
from the stored `v2` versus `v1` comparison (section 7).

---

## 6. Every new or changed file explained

### 6.1 Repository root and documentation

| File | Purpose |
|---|---|
| `CLAUDE.md` | Status log updated after every step; new lessons recorded (never use `on`/`off`/`yes`/`no` as YAML keys; absolute paths in PowerShell file operations). |
| `.env.example` | New settings: `REGGUARD_DATABASE_URL`, `REGGUARD_RECORD_HISTORY`, `REGGUARD_SLACK_WEBHOOK_URL` (empty: the real value goes only in `.env`). |
| `.claude/settings.json` | New rule: the AI assistant may not edit baseline files; they change only through the CLI. |
| `.github/workflows/ci.yml` | New `postgres` job: starts a PostgreSQL 16 server and runs the database tests against it. |
| `docs/adr/0002-file-baselines-in-ci.md` | Amended: baselines live next to the application's configuration (`examples/.../baselines/`). |
| `docs/adr/0005-history-and-drift.md` | New decision: history database (4 tables), SQLite/PostgreSQL, drift rules, web API moved to Phase 8. |
| `docs/slack-setup.md` | New: how to create a Slack webhook and keep it secret. |
| `docs/report/progress-report-phases-5-7.*` | This report. |

### 6.2 Example application (`examples/support-email-classifier/`)

| File | Purpose |
|---|---|
| `regguard.yaml` | Now also declares the baselines folder, the judge (`prompts/judge`, version `v2`), the gate thresholds, the drift settings (window 7, 3 consecutive runs) and the Slack events. |
| `prompts/judge/v1.yaml` | First judge prompt: 1 to 5 rubric, 3 worked examples, Nemotron with low reasoning effort. |
| `prompts/judge/v2.yaml` | Improved judge: personal data caps the score at 3, compliments are not required details, 5 worked examples. Used now. |
| `baselines/main.json` | The trusted baseline: prompt `v1` run `20261118T112032Z-a635b1`, graded by judge v2, promoted with the CLI. |

### 6.3 Backend configuration

| File | Purpose |
|---|---|
| `pyproject.toml` | New dependencies: SQLAlchemy, Alembic, Jinja2; optional `postgres` extra (`psycopg`). The layer rule now includes `comparison`, `reporting` and `notifications`. |
| `uv.lock` | Updated exact versions. |

### 6.4 Application code (`backend/src/regguard/`)

**`core/`: shared building blocks**

| File | Status | Purpose |
|---|---|---|
| `types.py` | changed | New data shapes: the ERROR verdict, judge results, baseline files, case changes, metric changes, comparisons with reasons, drift reports. |
| `gating.py` | **new** | The gate rules: thresholds per metric (warn, critical, unit, gating or not, tolerance), default values, significance level, minimum regressed cases, format floor, drift settings. |
| `config.py` | changed | New settings: database address, record history on/off, reports folder, Slack webhook (stored as a secret that is hidden in logs). |

**`apps/`**

| File | Status | Purpose |
|---|---|---|
| `config.py` | changed | Reads the new `regguard.yaml` sections: baselines folder, judge, gate, notify. |

**`comparison/`: verdicts and drift (new package, pure logic)**

| File | Purpose |
|---|---|
| `stats.py` | The exact one-sided McNemar / sign test, and "how many regressions are needed to be significant". |
| `diff.py` | Case outcomes (majority vote over samples), pairing of cases, regressed/improved lists, paired rates and paired continuous scores. |
| `thresholds.py` | Shared helpers: compute a change, decide whether a threshold is crossed, format a change. Used by both verdicts and drift. |
| `verdict.py` | The comparison itself: metric by metric, evidence, hard rules, reasons, final verdict. |
| `drift.py` | Comparable-run key, fresh-run check, moving average, consecutive rule, new episode, drift report. |

**`metrics/`**

| File | Status | Purpose |
|---|---|---|
| `base.py` | changed | A metric may now answer "not applicable". |
| `deterministic.py` | changed | `label_exact` is not applicable when the answer is unreadable. |
| `summary.py` | **new** | `summary_format` (one sentence, 5 to 40 words, not copied) and `summary_similarity` (word overlap). |
| `classification.py` | **new** | Precision, recall, F1 per category, macro F1. |
| `judge.py` | **new** | The judge's answer format (score 1 to 5 plus reason), its strict reading, and the `summary_judge` score. |
| `aggregate.py` | changed | New totals: precision and F1 per category, macro F1, judge error rate, judge tokens. |
| `registry.py` | changed | Adds the summary metrics to the email classifier. |

**`evaluation/`**

| File | Status | Purpose |
|---|---|---|
| `executor.py` | changed | Longer waits for server errors; new `CallBudget`, a hard cap on real API calls including retries. |
| `judge.py` | **new** | Builds the judge request and grades one summary. |
| `runner.py` | changed | Calls the judge after a valid answer; records judge provenance and statistics; run is ERROR if the judge fails too often. |

**`storage/`**

| File | Status | Purpose |
|---|---|---|
| `baseline_store.py` | **new** | Save, load and list baseline files; checks baseline names. |
| `db/models.py` | **new** | The 4 database tables. |
| `db/session.py` | **new** | Connects to the database, runs migrations from Python, upgrades local SQLite automatically, refuses an outdated server database. |
| `db/repository.py` | **new** | All database reads and writes (record a run or comparison, list runs, metric trends). |
| `db/migrations/` | **new** | The migration environment and the first migration `0001_history`. |

**`services/`: use cases**

| File | Status | Purpose |
|---|---|---|
| `run_service.py` | changed | Loads the judge prompt, counts judge calls in the estimate, shares one rate limiter and one call budget between classifier and judge. |
| `compare_service.py` | **new** | Promote a baseline, load the reference (baseline or another run), compare, save the comparison. |
| `history_service.py` | **new** | Record runs and comparisons (database errors become warnings), import old files, list, trends, upgrade. |
| `drift_service.py` | **new** | Load comparable history and compute the drift report. |
| `report_service.py` | **new** | Gather everything a report needs (emails only if the dataset is unchanged, trends from history) and write the HTML and Markdown files. |
| `notify_service.py` | **new** | Decide whether an event deserves a Slack message (PASS never, drift only at the start of an episode), send it, and report the outcome without ever raising an error. |

**`reporting/`: turning results into documents (new package, pure logic)**

| File | Purpose |
|---|---|
| `html.py` | Prepares the report data (case views, metrics, trends) and renders the template with automatic escaping. |
| `templates/report.html.j2` | The HTML page layout and styles (light and dark mode, no JavaScript). |
| `markdown.py` | The short Markdown summary for pull requests, with escaping and a limit of 10 cases. |
| `svg.py` | Draws a small trend line (sparkline) from a list of numbers. |

**`notifications/`**

| File | Status | Purpose |
|---|---|---|
| `slack.py` | **new** (was empty) | Builds the Slack messages (comparison, run error, drift, connection test), escapes text, and sends them over HTTPS without ever revealing the webhook address. |

**`providers/`**

| File | Status | Purpose |
|---|---|---|
| `factory.py` | changed | The mock provider can now answer differently for the classifier and the judge (used by tests and demos). |

**`cli/`**

| File | Status | Purpose |
|---|---|---|
| `main.py` | changed | New commands: `baseline promote/list/show`, `compare`, `report`, `history import/list/trend`, `drift`, `db upgrade`, `notify test`. New options on `run`: `--baseline`, `--fail-on-warn`, `--allow-dataset-change`, `--judge/--no-judge`, `--report`, `--notify`. Displays a judge column and a `Budget:` line. Report and notification always happen before the exit code is returned. |

### 6.5 Tests (`backend/tests/`)

| File | What it checks |
|---|---|
| `run_factory.py` | Helper that builds realistic fake runs for comparison and report tests. |
| `test_comparison_stats.py` | The significance test against known values. |
| `test_comparison.py` | Every verdict path: thresholds, evidence, hard rules, critical cases, ERROR, dataset change, judge change, continuous scores. |
| `test_baselines.py` | Promoting, loading and listing baselines; invalid names; refusing to overwrite. |
| `test_cli_compare.py` | The `baseline`, `compare` and `run --baseline` commands end to end, including exit codes. |
| `test_summary_metrics.py` | Summary format and similarity rules. |
| `test_classification.py` | Precision, recall, F1 and macro F1. |
| `test_judge.py` | Judge answer reading, judge errors, provenance, budget sharing. |
| `test_drift.py` | Comparable runs, fresh runs, moving average, consecutive rule, insufficient history, new episodes, gating-only status. |
| `test_db.py` | Database tables and migrations up and down, on SQLite and (in CI) on PostgreSQL. |
| `test_history.py` | Recording, import, trends, and "database failure is only a warning". |
| `test_reporting.py` | HTML escaping (no injected code), no JavaScript, Markdown content, and a golden file for the FAIL summary. |
| `test_notifications.py` | Slack messages and escaping, event rules, the webhook never appearing in output, and loading the real `regguard.yaml`. |
| `golden/summary_fail.md` | The expected Markdown summary for a FAIL comparison. |
| Existing files | Updated for the new behaviour (executor budget, judge in runs, new data types). |

---

## 7. Real results obtained

All results below come from the real AI (OpenRouter, Gemma 4 26B for classification,
Nemotron 3.5 Super as judge) on the 12-case balanced sample (3 emails per category).

### 7.1 The regression demo: prompt v2 versus prompt v1 (Phase 5a)

Prompt `v1` was promoted as baseline `main`. Then the deliberately minimal prompt `v2` was run
and compared:

| Metric | Baseline (v1) | Candidate (v2) | Change |
|---|---|---|---|
| Format valid (`schema_valid`) | 100% | 66.7% | −33.3 points (4 regressed, 0 improved, p = 0.062) |
| Correct category (`label_exact`), on readable answers | 100% | 100% | none |
| Summary format | 100% | 100% | none |
| Judge score (1 to 5) | 4.75 | 4.75 | none (same judge) |
| Tokens per case | 412 | 140 | −66% |

**Verdict: FAIL, exit code 4**, for two reasons:
`critical_regression` (format validity dropped far beyond the threshold, with significant
evidence) and `schema_valid_floor` (66.7% is below the 95% minimum).

What happened: on 4 emails, `v2` made the model return its answer inside a list,
`[{"category": ...}]`, instead of a plain object. A program reading that answer would crash.
The category inside was even correct, which is exactly the kind of silent breakage that
average accuracy hides. Note also the token drop: `v2` is much cheaper, which is the
tempting reason a team would ship it.

### 7.2 Summary metrics (Phase 5b-1, 0 API calls)

Rescoring from cache confirmed the verdict. `summary_similarity` stayed around **0.46 to 0.51**
even for good summaries: the model writes "The customer is asking..." while references say
"Customer asks...". Word overlap cannot tell a good summary from a bad one, so it stays
informational.

### 7.3 The AI judge (Phase 5b-2)

| Step | Judge calls | Result |
|---|---|---|
| Judge v1, first run | 20, 0 errors | Average 4.67 for v1. Agreed with a human reading on 11 of 12. Miss: gave 5/5 to a summary containing a customer's full name. |
| Judge v2 re-score | 20, 0 errors | That summary now 3/5 ("capped at 3 because it includes the sender's personal name"). A summary penalised for omitting a compliment went from 4 to 5. The other 10 scores did not move. **Agreement: 12 of 12.** |

The v1 run graded by judge v2 (average 4.58) was promoted as the new baseline `main`.
The judge stays **non-gating**: it has never yet been shown a really bad summary, so we have
not proven it gives low scores when it should (section 11).

### 7.4 History import and drift (Phase 6)

`history import` loaded **12 runs and 5 comparisons** from the existing files, with 0 API
calls. `drift` answered **INSUFFICIENT**: all earlier runs reused cached answers, and cached
answers cannot reveal drift. This is the intended behaviour: the system refuses to claim
"no drift" without real evidence.

### 7.5 First monitoring run: a real provider incident (20 November)

Command: `run -p v1 --limit 12 --no-judge --cache refresh` (fresh calls, for drift).

| What happened | What the system did |
|---|---|
| Google's servers answered HTTP 503 "high demand" repeatedly. | Retried with growing waits: 24 retries in total. |
| 2 cases still failed after 4 retries each (17% of cases). | Marked the run **ERROR** (above the 10% limit), not a quality drop. |
| The run was in ERROR. | Drift detection ignored it, as designed. |
| 12 planned calls turned into **36 real calls**. | Revealed a gap: retries were not budgeted. **Fixed the same day** (hard call cap, section 5). |

### 7.6 First real report (Phase 7)

`regguard report 20261118T112155Z` (0 API calls) produced
`reports/20261118T112155Z-edd66e.html` and `.md` from the stored v2 versus v1 comparison. The
Markdown summary is shown in full below; it is exactly what a GitHub comment will look like in
Phase 9.

```
## ❌ RegressionGuard: FAIL
App support-email-classifier · prompt v2 vs baseline main (v1) · model gemma-4-26b · 12 cases
Why
- FAIL critical_regression: schema_valid 100.0% → 66.7% (-33.3 pts), 4 regressed / 0 improved of 12, p=0.062
- FAIL schema_valid_floor: schema_valid 66.7% is below the floor of 95%
Changed cases: email-0012, email-0015, email-0017, email-0023 (regressed, schema_valid)
```

The HTML version was checked automatically: it contains no `<script>`, includes the trend
lines and the 4 regressed emails side by side. Slack sending is fully tested with a simulated
Slack. The real connection test waits for the webhook setup (section 11).

---

## 8. Difficulties met and how they were solved

| # | Difficulty | Cause | Solution |
|---|---|---|---|
| 1 | Should a 2-case drop on 12 cases fail a change? | With 12 cases, one case is 8.3 points, so any fixed percentage threshold fires on noise. | Two conditions: the drop crosses the threshold **and** there is evidence (p < 0.10 or at least 3 regressed cases). Each comparison states how many regressions would be needed for significance. |
| 2 | An unreadable answer was counted as wrong twice (format **and** category) | `label_exact` scored invalid answers as wrong. | "Not applicable" scores: the format failure is counted once, by `schema_valid`. |
| 3 | 8 retries in the Phase 5a demo for 12 cases | Waits after server errors (5xx) were too short. | Server errors now wait longer (2 s base, with random spread). |
| 4 | Word overlap could not judge summaries (about 0.5 even when good) | Different wording for the same meaning. | Kept as information only; an AI judge grades meaning. Embeddings were rejected (very large install, blocked risk under Smart App Control). |
| 5 | Judge model could "think" for a long time (hidden reasoning tokens) | Nemotron is a reasoning model (seen in Phase 2). | `reasoning: {effort: low}` in the judge prompt file and a token limit. |
| 6 | A broken judge could have made the application look worse | An unreadable judge answer could be mistaken for a low grade. | It is recorded as a judge error. Too many judge errors put the run in ERROR. |
| 7 | Judge gave 5/5 to a summary with a person's name | The rubric did not mention personal data. | Judge prompt v2 caps such summaries at 3. Agreement went from 11/12 to 12/12. |
| 8 | Comparing grades from two different judges would be meaningless | Changing the judge prompt changes the grades. | The comparison skips the judge score when the judges differ (`judge_changed`). The baseline was re-graded with judge v2. |
| 9 | Would a database library work under Windows Smart App Control? | Compiled packages and launchers can be blocked (ADR 0004). | A short test ("spike") before writing any code: SQLAlchemy and Alembic both worked, with migrations run from Python instead of a launcher. |
| 10 | An informational metric could fail a scheduled drift job | Drift initially used all metrics. | Each drift result says whether the metric is gating; only gating metrics decide the status. |
| 11 | Drift could not be tested on real data | All past runs used the cache. | Drift says INSUFFICIENT instead of OK. Fresh monitoring runs (`--cache refresh`) are needed; to be scheduled in Phase 9. |
| 12 | **12 planned calls cost 36 real calls** during a provider incident | Retries were not counted in the budget. | `CallBudget`: a hard cap on real calls, retries included, shared with the judge. The run stops cleanly when reached. The test was written so it does not really wait during retries. |
| 13 | Slack could have notified the whole channel | The message's fallback text was not escaped, so `<!channel>` in a name would ping everyone. | All Slack text is escaped, fallback text included, with a test. |
| 14 | **The real configuration failed to load** after adding Slack settings | In YAML 1.1 (used by PyYAML), the key `on:` is read as the boolean *true*. Tests built the configuration in Python and did not catch it. | Key renamed `events`; a new test loads the real `regguard.yaml`. Lesson recorded: never use `on`, `off`, `yes`, `no` as YAML keys. |
| 15 | Python suddenly could not import its own `html` module | A failed PowerShell command had created two empty files, `html.py` and `markdown.py`, in the backend folder; Python picked up the empty `html.py` instead of the standard one. | Found by verification, checked they were empty, deleted before any commit. Lesson recorded: always give absolute paths to .NET file functions in PowerShell. |
| 16 | Some typographic characters failed the style checker | En dashes and minus signs written directly in code. | Written as escape codes. |

---

## 9. Important design decisions

| Decision | Reason |
|---|---|
| **Alarm only on a large drop *with* evidence** (ADR 0003, implemented) | Prevents constant false alarms on a small dataset, without hiding real regressions: 3 or more broken cases always count. |
| **Paired, case-by-case comparison** rather than two averages | Shows exactly which emails broke; more sensitive, because it ignores cases that did not change. |
| **Hard rules beside statistics** (format floor, critical cases) | Some failures are unacceptable even once, whatever the statistics. |
| **Four verdicts, with ERROR separate from FAIL** | A provider outage must never look like "your prompt got worse" (exit 3 versus 4). |
| **Thresholds in configuration, with defaults** | Each team can tune them in `regguard.yaml`; the defaults work out of the box. |
| **Baselines changed only on purpose, through the CLI** | A baseline is a reviewed decision, not a side effect. The AI assistant is forbidden to edit them. |
| **The AI judge is non-gating until calibrated** | An uncalibrated grader must not block deployments. It becomes gating after a calibration set written by a human. |
| **The judge is versioned like a prompt, and recorded in each result** | Changing the judge changes the grades; results must say which judge produced them. |
| **Judge model from a different family than the classifier** | Reduces the bias of a model grading answers that look like its own. |
| **No embeddings, no SciPy** | Avoids very large dependencies and Smart App Control blocks; plain Python is enough. |
| **Files remain the source of truth for CI; the database is for history** (ADR 0005) | GitHub machines are temporary; files in the repository survive, and their changes are reviewable. |
| **4 database tables, not 11** | Prompts and datasets already live in git; copying them would create a second source of truth. |
| **A database failure is only a warning** | History is useful, but must never break a run or a verdict. |
| **Drift uses comparable, fresh runs only, and can say "insufficient"** | Comparing different prompts, or cached answers, would give meaningless or falsely reassuring results. |
| **One alert per drift episode** | Daily repeated alerts teach people to ignore the channel. |
| **The call budget is a hard cap, retries included** | Free plans allow about 50 calls a day; an outage must not silently burn the quota. |
| **No email text or model answers in Slack or Markdown** | Channels and pull requests are widely read; real emails contain personal data. Details stay in the HTML report. |
| **Notifications are opt-in, and never change the exit code** | Nobody is spammed by default, and Slack being down never blocks or unblocks a deployment. |
| **Web API moved to Phase 8** | The command line covers every need until the dashboard exists; building the API earlier would mean maintaining it with no user. |
| **Phase 9 (GitHub gate) before Phase 8 (dashboard)** | The automatic gate on pull requests is the core value of the project, and everything it needs exists now. |

---

## 10. Quality: how we know it works

| Indicator | End of Phase 4 | End of Phase 7 |
|---|---|---|
| Automated tests | 151 | **353** (+ 6 PostgreSQL tests run in CI) |
| Code exercised by tests | 95% | **96%** |
| Lines of application code | about 2,500 | about 5,500 |
| Lines of tests | about 1,650 | about 3,150 |
| Test duration | about 2 s | about 6 s |

- All checks pass (verified on 20 November 2026 with `uv run python scripts/check.py`):
  formatting, ruff, mypy in strict mode, the layer rule (1 contract kept, 0 broken), and pytest.
- **GitHub Actions** now has two jobs: the full checks on Python 3.12 and 3.14, and the
  PostgreSQL job.
- **Security-oriented tests:** HTML escaping with malicious email content, no JavaScript in
  reports, Slack mention escaping, the webhook address never printed, `https` only.
- **A golden file** protects the exact Markdown summary format, which GitHub comments will
  depend on.
- **Real-world verification** at every phase (section 7): the regression demo, the judge
  calibration, the history import, a real provider incident, a real report.
- **Bugs found by verification before they reached use**: the Slack escaping problem, the YAML
  `on:` key, the stray empty files, the unbudgeted retries.

---

## 11. What remains to do

### Next phases

| Phase | Content |
|---|---|
| **9** (next) | GitHub integration: on every pull request that changes a prompt or the dataset, run the evaluation, post the Markdown summary as a comment, and block the merge on FAIL. Plus a scheduled daily fresh run for drift detection. Needs the `gh` command-line tool. |
| 8 | Web API and dashboard: browse runs, comparisons, trends and drift in a browser. |
| 10 | Docker, security hardening, deployment. |
| 11 | Documentation, README, demo video. |

### Your pending actions

| Action | Why |
|---|---|
| Open `backend/reports/20261118T112155Z-edd66e.html` in a browser and give feedback. | I can check the HTML's content, but not how it looks on screen. |
| Set up Slack with `docs/slack-setup.md`, then `notify test`, then `compare 20261118T112155Z --notify`. | The real Slack connection has not been tested yet. |
| Check that both GitHub Actions jobs (backend and postgres) are green. | The PostgreSQL tests only run there. |
| Install the GitHub CLI: `winget install GitHub.cli`. | Needed for Phase 9. |

### Open improvements (optional)

- **Grow the golden dataset from 24 to 60 cases**, with more hard cases (ambiguous, typos,
  French/English, injection attempts). With 12 cases, 4 one-way regressions are needed for
  significance; more cases make the gate more sensitive.
- **Judge calibration set** (follow-up 3): about 8 deliberately flawed summaries with the
  expected scores, written by you, and a `regguard judge calibrate` command. This is the
  condition for making the judge gating.
- **Daily fresh monitoring run** (`run -p v1 --limit 12 --no-judge --cache refresh`) so drift
  detection gets real data; Phase 9 will schedule it.
- Remove "enjoys the application" from the reference summary of email-0011.
- A classifier prompt `v3` that forbids personal names in summaries.

---

## 12. How to run it

From the `backend` folder, in PowerShell. `-c` points to the application configuration:
`$c = "..\examples\support-email-classifier\regguard.yaml"`.

```powershell
# All quality checks (same as GitHub)
uv run python scripts/check.py

# Evaluate a prompt and compare it with the baseline, with report and Slack alert
uv run python -m regguard run -p v2 --limit 12 --baseline main --report --notify -c $c

# Baselines
uv run python -m regguard baseline list -c $c
uv run python -m regguard baseline show main -c $c
uv run python -m regguard baseline promote <run-id> --name main -c $c

# Compare a stored run (0 API calls), or two runs together
uv run python -m regguard compare <run-id> -c $c
uv run python -m regguard compare <run-id> --against <other-run-id> -c $c

# Reports for a stored run (0 API calls)
uv run python -m regguard report <run-id> -c $c

# History and drift
uv run python -m regguard history import
uv run python -m regguard history list
uv run python -m regguard history trend --metric label_exact
uv run python -m regguard drift -c $c
uv run python -m regguard run -p v1 --limit 12 --no-judge --cache refresh -c $c   # fresh run for drift

# Slack
uv run python -m regguard notify test
```

Exit codes: **0** PASS or WARN, **1** invalid input, **2** configuration error, **3** provider
problem or ERROR verdict, **4** gate FAIL (`--fail-on-warn` also fails on WARN).

The private `.env` file (repository root) holds the secrets: `REGGUARD_LLM_API_KEY` and,
optionally, `REGGUARD_SLACK_WEBHOOK_URL`. It is never committed.

---

## 13. Appendix: commit history

| Commit | Content |
|---|---|
| `de17c19` | Progress report for phases 0 to 4 |
| `dee0023` | Phase 5a: baselines, comparison and significance-aware gate; v1 baseline |
| `79f91f1` | Phase 5b-2: AI judge for summary quality (versioned prompt, separate executor, non-gating) |
| `a996442` | Phase 5: judge v2 calibrated; v1 baseline re-scored with judge v2 |
| `88fc4e6` | Phase 6: history database, history and trend commands, drift detection, PostgreSQL CI job |
| `0213b7b` | Fix: `--max-requests` is a hard cap on real API calls, retries included |
| `20ec324` | Phase 7: HTML and Markdown reports, Slack notifications (opt-in), `notify test` |

Phase 5b-1 (summary metrics, F1) was committed together with Phase 5b-2.
