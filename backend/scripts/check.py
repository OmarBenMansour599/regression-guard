"""Run every quality check, the same way CI does: ``uv run python scripts/check.py``.

Each tool runs via ``python -m`` so no generated .exe launchers are needed
(Windows Smart App Control blocks those; see docs/adr/0004).
"""

import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PY = sys.executable
LINT_IMPORTS = (
    "import sys; from importlinter.cli import lint_imports_command; "
    "sys.argv = ['lint-imports']; lint_imports_command()"
)

CHECKS: list[tuple[str, list[str]]] = [
    ("ruff format", [PY, "-m", "ruff", "format", "--check", "."]),
    ("ruff lint", [PY, "-m", "ruff", "check", "."]),
    ("mypy", [PY, "-m", "mypy"]),
    ("import layers", [PY, "-c", LINT_IMPORTS]),
    ("pytest", [PY, "-m", "pytest", "-q"]),
]


def main() -> int:
    failed: list[str] = []
    for name, cmd in CHECKS:
        print(f"\n=== {name} ===", flush=True)
        start = time.perf_counter()
        code = subprocess.call(cmd, cwd=BACKEND)  # noqa: S603 - fixed, trusted commands
        status = "ok" if code == 0 else f"FAILED (exit {code})"
        print(f"--- {name}: {status} in {time.perf_counter() - start:.1f}s", flush=True)
        if code != 0:
            failed.append(name)
    print("\nAll checks passed." if not failed else f"\nFailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
