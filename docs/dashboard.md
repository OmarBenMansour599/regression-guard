# Dashboard

A local, read-only web view of everything RegressionGuard records: runs, comparisons, trends, drift, baselines, prompts and the golden dataset. It reads the same history database the CLI writes, and changes nothing. Promoting a baseline or starting a run stays in the CLI, so every change remains a reviewed pull request (ADR 0007).

## Start it

From `regression-guard/`, in PowerShell:

```powershell
cd frontend; npm ci; npm run build          # once, and after each frontend change
cd ..\backend; uv sync --extra server        # once
uv run python -m regguard serve -c ../examples/support-email-classifier/regguard.yaml
```

Open **http://127.0.0.1:8000**. Stop with Ctrl+C. `--port 8080` picks another port.

The dashboard shows what is in the history database. If it is empty, import the run files saved on disk:

```powershell
uv run python -m regguard history import
```

## The pages

| Page | Shows |
|---|---|
| **Overview** | The latest verdict, the baseline, drift status, each prompt version's latest result, recent runs. |
| **Runs** | Every recorded run. Filter by prompt version and status; the filters are part of the address (bookmarkable). |
| **Run** | One run: provenance, metrics, every case. Open a case to see the email, the expected answer, the model's answer (or the raw unreadable output), the checks and the judge's grade. |
| **Compare** | Any run against a baseline or another run: verdict, reasons, metric changes, and each changed case side by side. Computed on the spot, never saved, same result as `regguard compare`. |
| **Trends & drift** | One metric over time. Filled points are fresh runs, hollow ones answers from the cache. By default it shows the baseline's prompt version; runs in ERROR and runs that scored no case are left out (the page says how many). Below: drift status per metric. |
| **Baselines & prompts** | Where each baseline comes from, every prompt version (the pinned one is marked), the dataset's balance. |

**How to read the colours.** Green, amber, orange and red only ever mean PASS, WARN, ERROR and FAIL, and always come with an icon and a word, never colour alone. A score drawn ~~struck through~~ belongs to a run that failed for technical reasons: only part of its cases were scored, so it is not a quality score.

## Privacy and security

It is a local tool without a login, and it shows email text.
- It listens on `127.0.0.1` only; `regguard serve --host 0.0.0.0` is refused (login and hosting come in Phase 10).
- Requests that do not address the server as `127.0.0.1` or `localhost` are refused, so a web page cannot reach it through DNS rebinding. No other site can read its answers (no CORS headers).
- Only GET requests exist: nothing can be changed through it.
- Email text is shown only when the dataset is unchanged since the run, and always as plain text (an email cannot inject code). A strict Content-Security-Policy forbids scripts from anywhere but the server itself.

## Speed

- The startup download is about **175 kB** compressed. Each page is a separate file loaded on demand, and the chart library loads only on Trends & drift.
- Build files have content fingerprints in their names and are cached by the browser for good. A rebuild produces new names, so a reload always gets the new version.
- API calls answer in 5 to 20 ms. Pages switch instantly from cache and refresh in the background.

## Develop it

```powershell
# terminal 1: the API on port 8000
cd backend; uv run python -m regguard serve -c ../examples/support-email-classifier/regguard.yaml
# terminal 2: the live-reloading frontend on http://127.0.0.1:5173 (calls are proxied to 8000)
cd frontend; npm run dev
```

| Check | Command (in `frontend/`) |
|---|---|
| Type check, lint, unit tests, build | `npm run check` |
| Browser tests (your installed Edge) | `npm run e2e -- --project=edge` |
| API types after a backend change | see below |

**API types.** The TypeScript types come from the API's OpenAPI description. After changing a response model in the backend:

```powershell
cd backend; uv run python -m regguard openapi --out ../frontend/openapi.json -c ../examples/support-email-classifier/regguard.yaml
cd ../frontend; npm run gen:api
```

CI fails if they are out of date.

**Adding a package.** `npm install <package>` updates `package-lock.json` incrementally, which has twice dropped packages that Linux needs, so `npm ci` failed in CI. After adding a package, rebuild the lock file and check it the way CI does:

```powershell
Remove-Item package-lock.json; Remove-Item -Recurse node_modules; npm install
npx -y npm@11 ci --ignore-scripts --dry-run
```

`.npmrc` keeps installs from running package scripts and pins exact versions.

## In CI

| Job | Checks |
|---|---|
| `frontend` | API types up to date, type check, lint, unit tests (Vitest), build |
| `e2e` | Builds the dashboard, seeds a history with the mock provider (no API key), then a real Chromium opens every page in light and dark mode. Fails on any console error or on a serious or critical accessibility problem (axe, WCAG 2 A/AA). |
