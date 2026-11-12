# RegressionGuard: Progress Report (Phases 0 to 4)

**Project:** Model Regression Detection System ("RegressionGuard")
**Author:** Omar Ben Mansour
**Period covered:** 9 to 12 November 2026
**Status:** Phases 0 to 4 complete (planning, foundation, LLM integration, golden dataset, evaluation engine). Next: Phase 5 (comparison and regression detection).

---

## Contents

1. The project in one page
2. Key words explained
3. How the system works (big picture)
4. Technology choices and why
5. What was built, phase by phase
6. Every file explained
7. Real results obtained
8. Difficulties met and how they were solved
9. Important design decisions
10. Quality: how we know it works
11. What remains to do
12. How to run it
13. Appendix: commit history

---

## 1. The project in one page

### The problem

Many applications now use a Large Language Model (LLM), such as the models behind ChatGPT
or Gemini, to do a task: answer customers, sort emails, extract information.

The behaviour of such an application is controlled by a **prompt** (the written
instructions given to the model) and by the **choice of model**. Teams change these all the
time to improve results or reduce costs. The danger is that a small change can silently make
the application **worse**:

- a reworded prompt starts putting emails in the wrong category;
- a new model returns its answer in a slightly different format, which breaks the program reading it;
- answers become slower or use more tokens (which costs more money).

In normal software, **automated tests** catch this kind of problem before it reaches users.
For LLM applications, most teams have no equivalent: they change the prompt and hope.

### The solution

RegressionGuard is an **automated testing system for LLM behaviour**. In simple terms:

> Every time someone changes a prompt or a model, RegressionGuard runs the application on a
> fixed set of carefully checked examples (the *golden dataset*), measures the quality of the
> answers, compares them with a trusted earlier version (the *baseline*), and raises an alarm
> if quality dropped. It can then block the change from being deployed.

A good analogy: a school exam with an answer key. The golden dataset is the exam with the
correct answers written by a human. Each new version of the prompt "sits the exam". If its
score drops compared to the previous version, we know the change made things worse, and we
know exactly which questions it now gets wrong.

### The first application we test

To build and demonstrate the system, we use a realistic example: a **customer-support email
classifier**. It reads a customer email and returns:

- a **category**: `billing`, `technical`, `account`, or `general`;
- a **one-sentence summary** of the email.

The system is designed so that other LLM applications can be added later without changing
the core engine.

### Where we are

The parts that **run** the evaluation are finished and tested with a real AI model:

- the system can call an AI model reliably, even on a free plan that frequently refuses requests;
- prompts and datasets are versioned like code;
- a human-labelled golden dataset exists (24 cases so far, target 60);
- a full evaluation run works end to end, saves its results, and was verified on the real API
  (12 out of 12 correct on a 12-case sample).

The parts that **compare** runs and **raise alarms** (the heart of regression detection)
are the next phase.

---

## 2. Key words explained

| Term | Simple meaning |
|---|---|
| **LLM** (Large Language Model) | An AI model that reads and writes text, such as Gemini or GPT. |
| **Prompt** | The written instructions sent to the LLM telling it what to do and how to answer. |
| **Provider / API** | The online service we send requests to and get answers from (here: OpenRouter). |
| **Token** | A small piece of text (roughly 3 to 4 characters). Providers count and bill usage in tokens. |
| **Latency** | How long one answer takes to arrive, in milliseconds. |
| **Golden dataset** | A fixed list of example inputs with the correct answers, written and checked by a human. It is the "answer key". |
| **Test case** | One example in the golden dataset: one email plus its correct category and summary. |
| **Evaluation run** | Running every test case through the AI and scoring each answer. |
| **Regression** | A change that makes results worse than before. |
| **Baseline** | A trusted earlier run that new runs are compared against. |
| **Schema / schema validation** | The exact expected shape of an answer (here: JSON with a `category` from 4 allowed values and a `summary`). Validation checks the answer has that shape. |
| **JSON** | A standard text format for structured data, e.g. `{"category": "billing", "summary": "..."}`. |
| **Hash** | A short "fingerprint" computed from a file's content. If one character changes, the fingerprint changes. Used to detect any modification. |
| **Cache** | A local memory of previous answers. Asking the exact same question again returns the stored answer instantly, without paying for a new API call. |
| **Rate limit / HTTP 429** | The provider refusing requests because too many arrive too quickly. |
| **HTTP 5xx (e.g. 504)** | A temporary failure on the provider's side (server overloaded or timed out). |
| **Retry with backoff** | Trying a failed request again after waiting, and waiting longer after each failure. |
| **CLI** (Command-Line Interface) | A program used by typing commands in a terminal, e.g. `regguard run -p v1`. |
| **CI** (Continuous Integration) | Automatic checks that GitHub runs on every code change (here: GitHub Actions). |
| **Commit / push** | Saving a snapshot of the code in git (commit), then uploading it to GitHub (push). |
| **Unit test** | A small automatic program that checks one piece of code behaves correctly. |
| **Mock provider** | A fake AI used in tests: it answers instantly and predictably, offline and free. |
| **ADR** (Architecture Decision Record) | A short document recording an important technical decision and why it was taken. |
| **PII** | Personally Identifiable Information: real emails, phone numbers, card numbers. Must not appear in test data. |

---

## 3. How the system works (big picture)

### 3.1 The flow of one evaluation run

When a developer types `regguard run -p v1`, the following happens:

1. **Load the configuration.** Read `regguard.yaml`, which says which application is tested
   and where its prompts and dataset are.
2. **Load the prompt version** (`v1.yaml`): instructions, examples, model name and settings.
   Compute its fingerprint (hash).
3. **Load and check the golden dataset** (`cases.yaml`): every case must be valid.
   Compute its fingerprint.
4. **Select the cases** to run (all, or a balanced subset such as 12 cases, 3 per category).
5. **Estimate the cost:** count how many real API calls are needed (cached answers are free)
   and refuse if this exceeds the allowed budget.
6. **Call the AI for each case**, carefully: at most 3 at a time, at most 15 per minute,
   retrying failures with increasing waits, and stopping early if the provider is clearly down.
7. **Check each answer:** is it valid JSON with the right shape? Is the category correct?
8. **Compute the totals:** pass rate, accuracy per category, speed, tokens, error rate.
9. **Decide the run status:** `COMPLETED`, or `ERROR` if too many calls failed for technical
   reasons (this is never confused with "the prompt got worse").
10. **Save everything** to a result file, including exactly which prompt, dataset, model and
    code version produced it, so the result can be reproduced and trusted.

Phase 5 will add step 11: **compare with the baseline and decide PASS / WARN / FAIL.**

### 3.2 How the code is organised

The code is one Python program (a "modular monolith") split into layers. Each layer may only
use the layers below it. This rule is checked automatically on every change.

```
  cli          what the user types (commands)
  services     the "use cases" that tie everything together
  evaluation   running cases: executor, cache, runner
  metrics      scoring answers
  apps         the application under test (email classifier)
  prompts | datasets | storage    prompt files, golden data, saved results
  providers    talking to the AI service
  core         shared building blocks (types, settings, errors, logging)
```

Why layers matter: the lower layers never depend on the upper ones, so each part can be
tested on its own, and replacing one part (for example, adding a web interface later) does
not require rewriting the others.

---

## 4. Technology choices and why

| Need | Choice | Why this one |
|---|---|---|
| Language | **Python** (3.14 locally, 3.12+ supported) | The standard language for AI tooling. |
| Package/environment manager | **uv** | Fast, reproducible installs with a lock file. |
| Data validation | **Pydantic** | Checks that every piece of data has the right shape and gives clear errors. |
| Command-line interface | **Typer** | Clean, typed commands with automatic help. |
| HTTP calls to the AI | **httpx** | Small library giving full control of timeouts and errors (the official SDKs hide their own retries, which would interfere with ours). |
| AI provider | **OpenRouter** (OpenAI-compatible API) | One account gives access to many models, including free ones. Groq would also work without code changes. |
| Classifier model | **Google Gemma 4 26B** (`google/gemma-4-26b-a4b-it:free`) | Free, fast, supports JSON output mode. |
| Judge model (Phase 5) | **NVIDIA Nemotron 3.5 Super** | Larger and from a *different* model family, to reduce the bias of a model grading itself. |
| Configuration files | **YAML** | Easy for humans to read and write, including multi-line emails. |
| Logging | **structlog** | Structured logs that are readable for humans and for machines. |
| Tests | **pytest** | The standard Python test framework. |
| Code quality | **ruff** (style and errors), **mypy** (type checking, strict mode), **import-linter** (layer rules) | Catch mistakes automatically before they become bugs. |
| Continuous integration | **GitHub Actions** | Runs all checks on every push, on Python 3.12 and 3.14. |

Deliberately **not** used (to avoid unnecessary complexity): microservices, Redis, Celery,
Kubernetes, LiteLLM, DeepEval, RAGAS. They are not needed at this scale; the reasons are in
the technical plan.

---

## 5. What was built, phase by phase

The project roadmap has 12 phases (0 to 11). Phases 0 to 4 are done.

### Phase 0: Planning and environment

**Goal:** understand the problem, challenge the initial idea, and design the system before
writing code.

**What we did:**

- Wrote a complete technical plan (`docs/technical-plan.md`): requirements, architecture,
  database design, folder structure, roadmap, risks.
- Questioned some initial assumptions and improved them (see section 9). The most important:
  fixed thresholds such as "warn at 3%, fail at 8%" produce false alarms on small datasets,
  because one test case out of 80 is already 1.25%.
- Recorded the three main decisions as ADRs (see section 9).
- Set up the repository: git, GitHub (private), `.gitignore`, Claude Code permissions, and a
  `CLAUDE.md` file that keeps the project rules and the current status.
- Installed the tools (uv).

**Result:** an agreed plan and a clean repository.

### Phase 1: Project foundation

**Goal:** a project that installs, runs, and is automatically checked.

**What we built:**

- The Python project configuration (`pyproject.toml`) and locked dependencies.
- The shared building blocks in `core/`: settings read from environment variables (secrets
  never written in files), error types, structured logging, and the shared data types that
  describe a run and its results.
- A first command, `regguard --version`.
- 18 unit tests, and the GitHub Actions workflow that runs all checks on every push.

**Result:** all checks green locally and on GitHub.

### Phase 2: Talking to the AI and managing prompts

**Goal:** send a versioned prompt to a real model and get a validated answer.

**What we built:**

- A **provider** that talks to any OpenAI-compatible service (OpenRouter, Groq). It makes
  exactly one attempt per call and reports clearly whether a failure is worth retrying.
- A **mock provider** (fake AI) so tests run offline, instantly and for free.
- **Versioned prompts:** each prompt version is one YAML file (`v1.yaml`, `v2.yaml`) containing
  the instructions, examples, model name and settings. A fingerprint (hash) detects any change
  that affects behaviour, while ignoring cosmetic edits such as the description.
- **The email classifier definition:** the exact answer shape (4 allowed categories plus a
  summary), and robust reading of the AI's answer (plain JSON, JSON inside code fences, or
  JSON surrounded by text).
- Commands: `regguard prompt list`, `regguard prompt show v1`, `regguard try` (classify one email).
- Two prompt versions: `v1` (detailed, with category definitions and examples) and `v2` (a
  deliberately short version, expected to perform worse, useful later to demonstrate regression
  detection).

**Result:** 81 tests passing; a real call to the AI returned a valid, correct answer.

### Phase 3: The golden dataset

**Goal:** a reliable, human-checked answer key, and tools to keep it correct.

**What we built:**

- The **test case format**: id, email, correct category, reference summary, difficulty
  (easy/medium/hard), tags (e.g. `typo`, `ambiguous`, `mixed_language`), a `critical` flag for
  must-never-fail cases, and notes.
- A **loader** that checks every case and reports *all* problems at once (useful because cases
  are written by hand).
- A **dataset fingerprint**: changing a label changes it, editing a note does not.
- **Safety and quality checks:** warnings for real-looking personal data (emails, phone numbers,
  card numbers, bank accounts), too few cases, unbalanced categories, duplicates, multi-sentence
  summaries, hard cases without explanation.
- **Balanced selection:** run a subset (e.g. 12 cases) that keeps the same number per category.
- Commands: `regguard dataset list | validate | stats`.
- A **labelling guide** (`docs/labeling-guide.md`): category definitions, tie-break rules for
  ambiguous emails, how to write summaries, difficulty levels, target distribution, process.
- **The dataset itself:** written by hand, not by an AI (this is what makes it trustworthy).
  24 cases written so far (batches 1 and 2); the first batch was reviewed for consistency.

**Result:** 114 tests passing; the dataset validates.

### Phase 4: The evaluation engine

**Goal:** run the whole dataset through the AI reliably and save complete, reproducible results.

**What we built:**

- **Executor** (the part that makes the calls):
  - at most 3 calls at the same time, and at most 15 per minute (the free plan allows 20);
  - automatic retries with waits that grow after each failure, respecting the provider's
    "retry after N seconds" instruction;
  - longer waits for rate limits (from 2.5 s up to 40 s) than for short glitches;
  - early stop of the whole run if the API key is rejected or after 5 consecutive failures,
    so the daily quota is not wasted.
- **Response cache:** an identical request is answered from disk. Three modes: normal
  (`read-write`), force fresh calls (`refresh`), disabled (`off`).
- **Budget guard:** before calling anything, the tool shows how many real calls are needed and
  refuses if it exceeds the limit (default 50, the free daily quota).
- **Metrics:** `schema_valid` (answer has the right shape) and `label_exact` (category correct),
  plus totals: pass rate, accuracy per category, speed (median and 95th percentile, counting
  only fresh calls), tokens.
- **Separation of technical failures and quality:** a case that failed for technical reasons is
  marked `ERROR` and excluded from accuracy. If more than 10% of cases fail technically, the
  whole run is marked `ERROR`, never counted as a quality drop.
- **Full traceability:** each result records the prompt and dataset fingerprints, the model
  requested, whether it was overridden, the model the provider says it used, the git version of
  the code (marked `-dirty` if uncommitted changes exist), and the number of calls, cache hits
  and retries.
- **Saved results** in `runs/<run-id>/result.json`.
- Commands: `regguard run`, `regguard runs list`, `regguard runs show <id>`.

**Result:** 151 tests passing (95% of the code exercised by tests), and the real-API acceptance
test passed (section 7).

---

## 6. Every file explained

Files marked *(empty, later phase)* exist in the folder structure but have no content yet.

### 6.1 Root of the repository

| File | Purpose |
|---|---|
| `CLAUDE.md` | The project's rulebook and logbook: working rules, architecture rules, commands, environment notes, and the up-to-date status (done / pending / next). Read automatically by the AI assistant. |
| `README.md` | *(empty, Phase 11)* Will become the onboarding guide for a new team member. |
| `.env.example` | Template listing the settings (API key, provider address, limits). The real values go in a private `.env` file that is never uploaded. |
| `.gitignore` | Tells git which files never to save: secrets (`.env`), temporary files, local results (`runs/`), the cache. |
| `.gitattributes` | Makes line endings consistent between Windows and Linux. |
| `.pre-commit-config.yaml` | Optional checks run before each commit, including a scanner that blocks accidentally committed secrets (gitleaks). |
| `docker-compose.yml` | *(empty, Phase 10)* Will start the full system in containers. |
| `.claude/settings.json` | Permissions for the AI coding assistant: what it may run freely (tests, linters) and what it must never touch (the `.env` file, destructive commands). |
| `.github/workflows/ci.yml` | The GitHub Actions workflow: on every push, installs the project and runs all checks on Python 3.12 and 3.14. |

### 6.2 Documentation (`docs/`)

| File | Purpose |
|---|---|
| `technical-plan.md` | The full engineering plan: analysis, architecture, stack, database design, roadmap, risks, decisions. |
| `labeling-guide.md` | How to write golden test cases: category definitions, tie-break rules, summary rules, difficulty, quotas, process. |
| `adr/0001-modular-monolith.md` | Decision: one well-organised program instead of many services. |
| `adr/0002-file-baselines-in-ci.md` | Decision: baselines are files saved in the repository (so GitHub can compare without a server); history goes in a database later. |
| `adr/0003-significance-aware-gating.md` | Decision: only fail a change when the drop is both large enough *and* unlikely to be random noise. |
| `adr/0004-python-version-and-smart-app-control.md` | Decision: use the signed Python 3.14 locally because Windows security blocked the unsigned one. |
| `architecture.md` | *(empty)* Will hold the living architecture description. |
| `report/progress-report.md`, `.tex`, `.pdf` | This report. |

### 6.3 Example application (`examples/support-email-classifier/`)

| File | Purpose |
|---|---|
| `regguard.yaml` | Configuration of the tested application: its name, which code describes it, where the prompts and dataset are, and which model acts as the judge. |
| `prompts/classify/v1.yaml` | Prompt version 1: detailed instructions, category definitions, protection against instructions hidden in emails, 2 worked examples, model and settings. |
| `prompts/classify/v2.yaml` | Prompt version 2: a deliberately minimal prompt, used later to demonstrate that regressions are detected. |
| `datasets/emails/v1/dataset.yaml` | Description of dataset version 1 (name, version, date, change log). |
| `datasets/emails/v1/cases.yaml` | The golden test cases written by hand (24 so far). |

### 6.4 Backend configuration and scripts (`backend/`)

| File | Purpose |
|---|---|
| `pyproject.toml` | Project definition: dependencies, the `regguard` command, and the settings of all quality tools, including the layer rules. |
| `uv.lock` | Exact versions of every dependency, so every install is identical. |
| `.python-version` | Python version used locally (3.14). |
| `scripts/check.py` | Runs every quality check in one command, exactly like GitHub does: formatting, lint, type checking, layer rules, tests. |
| `alembic.ini` | *(empty, Phase 6)* Will configure database migrations. |
| `CLAUDE.md` | *(empty)* Reserved for backend-specific assistant rules. |

### 6.5 Application code (`backend/src/regguard/`)

**Package entry points**

| File | Purpose |
|---|---|
| `__init__.py` | Holds the version number (0.1.0). |
| `__main__.py` | Allows starting the tool with `python -m regguard`. |

**`core/`: shared building blocks used everywhere**

| File | Purpose |
|---|---|
| `config.py` | Reads settings from environment variables and the `.env` file (API key, provider address, limits, folders). The API key is hidden in logs. |
| `errors.py` | The list of error types (configuration error, invalid data, provider error with "worth retrying?" information, comparison error). |
| `logging.py` | Sets up readable or machine-readable logs. |
| `types.py` | The shared data shapes: an AI answer, token usage, a score, a case result, run information, a full run result. Everything else uses these. |

**`providers/`: talking to the AI**

| File | Purpose |
|---|---|
| `base.py` | The common contract every provider follows ("send this request, return an answer") and the request format. |
| `openai_compatible.py` | The real provider: sends the request over HTTPS, measures time, reads tokens, and turns every failure (rate limit, timeout, server error, bad key) into a clear error saying whether retrying can help. |
| `mock_provider.py` | Fake AI for tests and demos: predictable, offline, free. |
| `factory.py` | Picks the real or the fake provider based on settings, and complains clearly if the API key is missing. |

**`prompts/`: versioned prompts**

| File | Purpose |
|---|---|
| `models.py` | The shape of a prompt file, its validation (placeholders must match declared inputs), and its fingerprint. |
| `loader.py` | Reads prompt files, checks the file name matches the version, lists available versions. |
| `render.py` | Builds the final messages sent to the AI by filling the email into the template (`$email`). |

**`apps/`: the application under test**

| File | Purpose |
|---|---|
| `base.py` | What describes an application (inputs, answer shape) and the robust reading of the AI's JSON answer. |
| `support_email.py` | The email classifier: the 4 allowed categories, the summary rules, an example answer for the mock. |
| `registry.py` | The list of known applications, found by name. |
| `config.py` | Reads `regguard.yaml` and resolves folder paths. |

**`datasets/`: the golden dataset**

| File | Purpose |
|---|---|
| `models.py` | The shape of a test case and of a dataset, and the dataset fingerprint. |
| `loader.py` | Reads and checks a dataset version, reporting all problems at once; finds the latest version. |
| `lint.py` | Privacy and quality warnings (personal data, imbalance, duplicates, multi-sentence summaries) and statistics. |
| `select.py` | Picks a balanced, repeatable subset of cases, or filters by id or tag. |

**`metrics/`: scoring answers**

| File | Purpose |
|---|---|
| `base.py` | The common contract every metric follows. New metrics plug in without changing the engine. |
| `deterministic.py` | The two current metrics: `schema_valid` and `label_exact`. No AI involved, fully reproducible. |
| `registry.py` | Which metrics apply to an application. |
| `aggregate.py` | Turns per-case scores into run totals: pass rate, per-category accuracy, speed percentiles, tokens, error rate. |

**`evaluation/`: running the cases**

| File | Purpose |
|---|---|
| `executor.py` | Makes the AI calls safely: concurrency limit, per-minute limit, retries with growing waits, early stop, statistics. |
| `cache.py` | Stores and reuses identical answers on disk, with three modes. |
| `runner.py` | For each case: build the request, call, read the answer, score it. Then compute totals and the run status. |

**`storage/`: saving results**

| File | Purpose |
|---|---|
| `file_store.py` | Saves runs as JSON files, creates run ids, loads a run by id (or the start of its id), lists runs. |

**`services/`: use cases that tie the layers together**

| File | Purpose |
|---|---|
| `invoke.py` | Classify one input once (used by `regguard try`). |
| `datasets.py` | Load the dataset of an application. |
| `run_service.py` | The full evaluation run: prepare, estimate the budget, execute, record the git version, save. |

**`cli/`: the commands**

| File | Purpose |
|---|---|
| `main.py` | All the commands: `--version`, `prompt list/show`, `try`, `dataset list/validate/stats`, `run`, `runs list/show`. It only handles input and display; the logic lives in the services. |

**`notifications/`**

| File | Purpose |
|---|---|
| `slack.py` | *(empty, Phase 7)* Will send alerts to Slack. |

### 6.6 Tests (`backend/tests/`)

| File | What it checks |
|---|---|
| `conftest.py` | Shared test helpers (paths, a clean environment without real settings). |
| `test_config.py` | Settings loading, `.env` discovery, the secret never appearing in logs. |
| `test_errors.py`, `test_logging.py`, `test_types.py` | Error types, log output, data shapes (round-trip to JSON, immutability). |
| `test_openai_compatible.py` | The real provider against simulated responses: success, rate limit, server error, bad key, timeout, malformed answers, readable error messages. |
| `test_mock_and_factory.py` | The fake provider and provider selection. |
| `test_prompts.py` | Prompt validation, fingerprints, rendering (including `$` and `{}` in emails). |
| `test_apps.py` | Reading AI answers (valid and invalid variants), application config. |
| `test_invoke.py` | The single-call service. |
| `test_datasets.py` | Dataset loading, errors, fingerprints, privacy checks, statistics, balanced selection. |
| `test_executor.py` | Retries, waits, early stop, per-minute limit, cache modes (with a fake clock so tests are instant). |
| `test_runner.py` | A full run with correct, wrong, invalid and failed answers; totals; run status; traceability. |
| `test_run_service.py` | Preparation, budget guard, saving, second run fully cached, empty selection refused. |
| `test_cli*.py` | Every command, end to end, with the fake provider; includes a test that the committed golden dataset is always valid. |

---

## 7. Real results obtained

### 7.1 First real call (Phase 2)

One email ("I was charged twice this month and need a refund") classified as `billing` with a
correct summary. It needed a different model temporarily, because the free Gemma models were
overloaded (section 8).

### 7.2 Acceptance test of the evaluation engine (Phase 4)

Command: `regguard run -p v1 --limit 12` (12 cases, 3 per category), on the real API.

| Run | Status | Real API calls | From cache | Correct | Explanation |
|---|---|---|---|---|---|
| 1 | ERROR | 30 (incl. 18 retries) | 0 | 10 of 10 answered | 2 cases failed with "HTTP 504" (provider timeout) after all retries. 17% technical failures > 10% limit, so the run is correctly marked ERROR, not counted as wrong answers. |
| 2 | COMPLETED | 3 | 10 | 12 of 12 | Only the 2 failed cases were called again. |
| 3 | COMPLETED | 0 | 12 | 12 of 12 | Fully reused: re-running an unchanged prompt costs nothing. |

Measured on fresh calls: about **1.5 seconds per answer**, about **410 tokens per case**
(of which about 25 are the answer itself).

What this demonstrates: the system survives an unreliable free service, never confuses
technical failures with quality problems, wastes no quota on repeated work, and records
enough information to trust and reproduce every result.

An earlier attempt (before the provider fix) is also instructive: every call was refused
(rate limit), the engine retried, then stopped the run early and marked it `ERROR`. The
safety mechanisms worked as designed.

---

## 8. Difficulties met and how they were solved

| # | Difficulty | Cause | Solution |
|---|---|---|---|
| 1 | The `uv` tool "not recognised" after installing it | The terminal kept the old list of program locations (PATH). | Restart VS Code completely (a new terminal tab is not enough). |
| 2 | Confusion between commit, push and GitHub | Git saves locally first; GitHub needs a repository and a push. | Created the private GitHub repository, then `git commit` and `git push`. |
| 3 | Installer refused the project (`README` outside the project folder) | Packaging tool rule. | Removed that setting. |
| 4 | **Windows Smart App Control blocked Python** (the tools stopped working two days after setup) | Windows switched this security feature to "enforce" mode; it blocks unsigned programs, including the Python downloaded by uv and the small launchers of tools such as mypy. | Diagnosed with the registry and signature checks. Switched to the already installed, officially signed Python 3.14; run every tool with `python -m ...`; install mypy from source. Did **not** disable the security feature (it cannot be turned back on without reinstalling Windows). Recorded as ADR 0004. GitHub still tests Python 3.12. |
| 5 | **Free AI model constantly refused requests (HTTP 429)** | The free Gemma models share one overloaded pool at Google for all OpenRouter users. Changing to another free Gemma model did not help (same pool). | Added your own free Google AI Studio key in OpenRouter ("BYOK"), so requests use your own quota. |
| 6 | Some requests failed with HTTP 504 (timeout) | Temporary overload on the provider side. | Automatic retries; failed cases are not cached, so re-running only retries those. |
| 7 | Retries were too fast for rate limits, wasting 32 calls | Waits of 0.1 to 7 seconds do not help when a pool is saturated for minutes. | Rate limits now wait 2.5 s, 5 to 10 s, 10 to 20 s, then 20 to 40 s. Logs shortened. |
| 8 | Temporary model had hidden "thinking" (132 tokens for a 25-token answer, 21 s) | Nemotron is a reasoning model. | Noted: reasoning must be controlled for the judge in Phase 5. Gemma does not have this issue. |
| 9 | Testing with a different model looked like a normal `v1` run | The temporary model override did not change the recorded prompt fingerprint. | Results now record the model actually used, an "override" flag, and the model the provider says it served. |
| 10 | A JSON list was wrongly accepted as a valid answer | Overly lenient answer parsing. | Found by a test; fixed. |
| 11 | A selection matching 0 cases reported "COMPLETED, 0%" | Missing check. | Empty selections are now refused with a clear message. |
| 12 | GitHub showed red failures on every push | An empty placeholder workflow file (`evaluate.yml`) is invalid for GitHub. | Removed; the real one comes in Phase 9. |
| 13 | GitHub failed after the first real cases were committed | A test assumed the dataset would stay empty. | Replaced by a better test: the committed dataset must always be valid. |
| 14 | A test case could not be read | The email was written as two sub-fields (subject and body) instead of one text block. | Explained the format; the case was fixed. |
| 15 | Labelling guide contradicted itself on pricing questions | "prices" was listed under billing, but "student discount?" under general. | Added a rule: pricing questions from non-customers are `general`; questions about one's own charges are `billing`. |
| 16 | Dataset quality risks in batch 1 | 6 of 12 cases marked `critical` (target: about 6 in 60); every email had the same layout and a subject that gave away the answer. | Recommendations: keep 2 to 3 critical cases; vary the email form (no subject, vague subject, one line, typos, French/English). Added to the guide. |

---

## 9. Important design decisions

| Decision | Reason |
|---|---|
| **One well-organised program** (modular monolith), not microservices (ADR 0001) | Simpler to build, test and deploy for one developer; layers keep it clean. |
| **Command-line first**; GitHub uses the same commands | The core works without any server; the web dashboard comes later on top of it. |
| **Baselines are files in the repository** (ADR 0002) | GitHub's machines are temporary and cannot keep a database between runs; a file in the repository can, and changes to it are reviewable. |
| **Baseline chosen explicitly**, not "the previous run" | Comparing only with the previous run lets quality slowly slide: each small drop looks acceptable. |
| **Alarm only when the drop is large *and* not likely random** (ADR 0003) | With 60 to 100 cases, one case is 1 to 1.7%. AI answers also vary slightly between runs. Fixed thresholds alone would trigger constant false alarms. |
| **Technical failures are never quality failures** | A provider outage must not look like "your prompt got worse". |
| **The model and its settings live in the prompt file**, not in private settings | Changing the model is one of the changes we must detect and review. |
| **Retries happen in one place** (the executor) | Avoids retries stacking up, and keeps speed measurements honest. |
| **Human-written golden data, never AI-generated** | The answer key must be trustworthy; an AI cannot grade itself. |
| **One correct category per case**, with tie-break rules | Keeps accuracy clear; ambiguous cases are tagged and reported separately. |
| **YAML for the dataset** (not JSONL) | Multi-line emails are readable and easy to write by hand. |
| **Cache on by default, with a budget guard** | Free plans allow about 50 calls per day; repeated work must be free. Drift monitoring will force fresh calls. |
| **Python 3.14 locally, 3.12+ supported** (ADR 0004) | Required by Windows security; GitHub still tests 3.12. |

---

## 10. Quality: how we know it works

- **151 automated tests**, all passing, covering 95% of the application code. They run offline
  and in about 2 seconds, thanks to the fake provider and a fake clock.
- **Strict type checking** (mypy) on all code: many mistakes are caught before running anything.
- **Automatic layer check:** a lower layer can never accidentally depend on a higher one.
- **Style and error checks** (ruff), including security rules.
- **GitHub Actions** runs all of this on every push, on two Python versions.
- **The golden dataset is itself tested:** every push checks that all cases are valid.
- **Real-world verification** against the live AI (section 7), not only simulated tests.
- About 2,500 lines of application code and 1,650 lines of tests.

---

## 11. What remains to do

| Phase | Content |
|---|---|
| **5a** (next) | Comparison of two runs, baselines (`regguard baseline promote`), case-level regressions and improvements, thresholds per metric, statistical significance, critical-case rule, final PASS / WARN / FAIL. Demo: v2 compared against v1. |
| 5b | Summary quality (meaning-based similarity and an AI judge), precision / recall / F1 per category, slow-drift detection over many runs. |
| 6 | Database and history, web API. |
| 7 | HTML reports and Slack notifications. |
| 8 | Web dashboard. |
| 9 | GitHub integration: run automatically when a prompt changes, comment on the pull request, block merging on critical regressions. |
| 10 | Docker, security hardening, deployment. |
| 11 | Documentation, README, demo video. |

**Dataset work in progress:** 24 of the 60 target cases are written. The next batches should
add medium and hard cases (ambiguous, typos, French/English, sarcasm, injection attempts) and
reduce the number of `critical` cases.

---

## 12. How to run it

From the `backend` folder, in PowerShell:

```powershell
# Run every quality check (same as GitHub)
uv run python scripts/check.py

# Check the golden dataset
uv run python -m regguard dataset validate -c ..\examples\support-email-classifier\regguard.yaml
uv run python -m regguard dataset stats    -c ..\examples\support-email-classifier\regguard.yaml

# Classify one email
uv run python -m regguard try -p v1 -c ..\examples\support-email-classifier\regguard.yaml -i "I was charged twice"

# Evaluate prompt v1 on 12 balanced cases, then inspect results
uv run python -m regguard run -p v1 -c ..\examples\support-email-classifier\regguard.yaml --limit 12
uv run python -m regguard runs list
uv run python -m regguard runs show <run-id>
```

The private `.env` file (at the repository root) must contain the OpenRouter API key:
`REGGUARD_LLM_API_KEY=...`.

---

## 13. Appendix: commit history

| Commit | Content |
|---|---|
| `f6f0b71` | Phase 0: planning documents and repository setup |
| `e5a5b61` | Phase 1: foundation (core types, settings, logging, command line, CI) |
| `a1e9ceb` | Phase 2: AI providers, versioned prompts, `try` command |
| `ef595dc` | Phase 3: golden dataset tools, labelling guide, Python 3.14 (ADR 0004) |
| `f2e55f1`, `2454e41` | Dataset batch 1 (12 cases), guide clarifications, workflow fix |
| `a182f2c` | Phase 4: evaluation engine, fixes, dataset batch 2 |
