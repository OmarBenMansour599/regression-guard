"""Static checks of .github/workflows/*.yml that GitHub would only report after a push.

1. Expression contexts used where GitHub does not allow them (docs: "Context
   availability"). One violation makes the whole workflow invalid: none of its jobs run,
   and required checks wait forever (PR #7, 2026-11-26: `runner` in a job-level env).
2. ``${{ }}`` inside ``run:`` scripts: a script-injection risk; pass values through env.

Usage: ``uv run python scripts/check_workflows.py [workflows-dir]`` (part of check.py).
"""

import re
import sys
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
WORKFLOW_LEVEL = {"github", "vars", "secrets", "inputs"}
JOB_LEVEL = WORKFLOW_LEVEL | {"needs", "strategy", "matrix"}  # runner/env/steps/job: steps only
JOB_KEYS = ("env", "runs-on", "timeout-minutes", "concurrency", "defaults")
_CONTEXT = re.compile(r"\$\{\{\s*!?\s*\(?\s*([a-z_]+)")


def _contexts(value: object) -> list[str]:
    return _CONTEXT.findall(str(value))


def check(directory: Path) -> list[str]:
    problems: list[str] = []
    for wf in sorted(directory.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for ctx in _contexts(data.get("env", {})):
            if ctx not in WORKFLOW_LEVEL:
                problems.append(f"{wf.name}: workflow env uses '{ctx}'")
        for name, job in (data.get("jobs") or {}).items():
            for key in JOB_KEYS:
                for ctx in _contexts(job.get(key, "")):
                    if ctx not in JOB_LEVEL:
                        problems.append(
                            f"{wf.name}: jobs.{name}.{key} uses '{ctx}' (only allowed in steps)"
                        )
            for i, step in enumerate(job.get("steps", [])):
                if "${{" in str(step.get("run", "")):
                    problems.append(
                        f"{wf.name}: jobs.{name}.steps[{i}] has an expression inside run: "
                        "(pass it through env:)"
                    )
    return problems


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else WORKFLOWS
    problems = check(directory)
    for problem in problems:
        print(problem)
    if not problems:
        print(f"{len(list(directory.glob('*.yml')))} workflow files OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
