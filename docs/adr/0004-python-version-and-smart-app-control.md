# ADR 0004: Develop on signed system Python 3.14; support 3.12+

Status: Accepted (2026-11-12). Supersedes the "pin Python 3.12 via uv" note in the technical plan.

## Context
The development machine runs Windows 11 with Smart App Control in enforcement mode. It blocks
unsigned binaries: the uv-downloaded (python-build-standalone) Python 3.12 (`_ctypes.pyd`),
uv-generated `.exe` tool launchers, and mypy's compiled wheel modules. The python.org
Python 3.14 installed on the machine is signed and runs normally. Smart App Control cannot
be re-enabled once turned off, so disabling it is not an acceptable fix.

## Decision
- Local development uses the signed system Python 3.14 (`backend/.python-version` = 3.14).
- `requires-python` stays `>=3.12`; CI runs the full suite on 3.12 and 3.14.
- mypy is installed from source (`[tool.uv] no-binary-package`), which is pure Python.
- Tools run via `python -m ...`; `scripts/check.py` runs every check, locally and in CI.
  The CLI is also runnable as `python -m regguard`.

## Consequences
+ Works under Smart App Control without weakening machine security; no extra installs.
+ CI still proves the 3.12 minimum.
- mypy is slower (~10 s instead of ~2 s).
- Newly downloaded compiled wheels could still be blocked in future; the fix pattern is the same.
