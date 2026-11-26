# ADR 0007: Dashboard stack (Vite + React, served by FastAPI) and scope

Status: Accepted (2026-11-25)

## Context
The technical plan chose Next.js. Since then the CLI, the history database, the HTML report and the CI gate have covered every workflow that changes something. What is missing is a comfortable way to browse runs, comparisons, trends and drift. The development machine enforces Windows Smart App Control (ADR 0004), and current frontend tools ship unsigned native modules, so the stack had to be tried before being chosen.

## Decision
- **A single-page app (Vite, React, TypeScript), served by FastAPI** with `regguard serve`: one process, no Node server at run time. Next.js is dropped: server rendering brings nothing to a local, read-only tool and would need its own server.
- **Read-only.** Promoting a baseline stays a reviewed git change (ADR 0002). Starting runs from a web page would need a job queue and could spend the API quota by accident. Pages show the matching CLI command instead.
- **Local only for now**: binds to `127.0.0.1`, no login. The API returns email text, so it also checks the `Host` header (a web page must not reach it through DNS rebinding) and sends no CORS headers. FastAPI's `/docs` page is off, because it loads scripts from a CDN. Login and hosting come in Phase 10.
- **TypeScript types are generated from the API's OpenAPI description** (`openapi-typescript`); CI fails when they are out of date.
- **Server packages are an optional extra** (`uv sync --extra server`); the CLI and the CI gate do not need them.

## Spike results (2026-11-25, Smart App Control enforcing)
| Check | Result |
|---|---|
| Native modules (Rolldown, Tailwind Oxide, Lightning CSS: all unsigned) | load; 0 blocks in the Windows Code Integrity log |
| Build, type check, lint, Vitest + jsdom | all pass; build 0.4 s, tests 1.2 s |
| `npm install --ignore-scripts` | enough: no package needs its install script |
| FastAPI 0.165 + uvicorn 0.54 on Python 3.14 | one process serves the API and the app; inner URLs open directly; unknown `/api/` paths return 404 |
| OpenAPI to TypeScript types | generated and type-checked |
| Seen in a real browser (Playwright with the installed Edge) | page, chart and API call work; clean console |

Version limits found:
- **TypeScript 5.9, not 7**: `openapi-typescript` needs `^5`, `typescript-eslint` needs `<6.1`.
- **jsdom 27, not 31**: jsdom 31 needs Node 24.15 or newer; the machine has 24.13.

## Results (Phase 8 done, 2026-11-26)
- **Startup download**: 582 kB → 174 kB, from gzip compression on the server (it was sending uncompressed). Build files get `Cache-Control: immutable`, since their names carry a content hash; the app shell gets `no-cache`. Measured: first page ready in about 110 ms, a second visit in about 30 ms, API routes 5 to 20 ms on the server.
- **Accessibility**: an axe WCAG 2 A/AA audit runs on every page, in light and dark mode, in CI. It found and we fixed:
  - text contrast under 4.5:1 (struck-through scores, small version text, inactive filter buttons, "(info)" in badges);
  - tabs used without tab panels (replaced by a toggle group);
  - `aria-expanded` on table rows;
  - scrollable email and raw-output boxes that could not be reached by keyboard.
- **Server**: the security and cache headers became plain ASGI middleware, because `@app.middleware("http")` raised "No response returned" when the browser cancelled a request.

## Consequences
+ One command starts everything; the CLI and CI are unchanged.
+ Frontend types cannot drift from the API unnoticed.
- Two toolchains (uv and npm). All frontend versions are locked; CI uses `npm ci --ignore-scripts`.
- Smart App Control decides by reputation, so a brand-new release of a native module could be blocked one day. Keep versions locked; upgrade on purpose.
- Recharts makes the bundle large (about 195 kB compressed): load chart pages on demand.
