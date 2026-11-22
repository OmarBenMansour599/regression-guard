"""CI use cases (Phase 9): decide what a pull request needs evaluated, then summarize the gate.

``plan_ci`` maps the files changed by a pull request to the prompt versions to evaluate.
``collect_outcomes`` + ``gate_verdict`` + ``render_pr_comment`` turn the runs made by the
workflow into one verdict and one PR comment. The workflow itself only runs commands; every
decision lives here, where it is tested.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from regguard.apps.config import AppConfig
from regguard.core.errors import DataValidationError
from regguard.core.types import Comparison, FrozenModel, RunResult, RunStatus, Verdict
from regguard.reporting.markdown import md, render_markdown
from regguard.storage.baseline_store import load_baseline
from regguard.storage.file_store import list_runs

# Hidden marker: the workflow finds and edits its own comment instead of adding a new one.
COMMENT_MARKER = "<!-- regressionguard:pr-gate -->"
# Free tiers allow ~50 calls/day; one prompt costs ~12 calls without the judge.
MAX_PROMPTS = 3
_PROMPT_SUFFIXES = (".yaml", ".yml")
_ICONS = {Verdict.PASS: "✅", Verdict.WARN: "⚠️", Verdict.FAIL: "❌", Verdict.ERROR: "🛑"}


class CiPlan(FrozenModel):
    """What a pull request needs. ``blocking`` fails the gate without evaluating anything."""

    baseline: str = "main"
    prompt_versions: tuple[str, ...] = ()
    dataset_changed: bool = False
    config_changed: bool = False
    baselines_changed: tuple[str, ...] = ()
    judge_changed: bool = False
    blocking: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def evaluate(self) -> bool:
        return self.blocking is None and bool(self.prompt_versions)

    @property
    def relevant(self) -> bool:
        """True when the PR touches anything the gate cares about."""
        return bool(
            self.prompt_versions
            or self.dataset_changed
            or self.config_changed
            or self.baselines_changed
            or self.judge_changed
            or self.blocking
        )


def find_repo_root(start: Path) -> Path:
    """The nearest parent containing ``.git`` (git paths are relative to it); else ``start``."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _under(path: Path, directory: Path | None) -> bool:
    return directory is not None and path.is_relative_to(directory)


def plan_ci(
    config: AppConfig,
    config_path: Path,
    changed_paths: Iterable[str],
    *,
    repo_root: Path,
    baseline: str = "main",
) -> CiPlan:
    """Map changed files (relative to ``repo_root``, as ``git diff --name-only`` prints them)."""
    root = repo_root.resolve()
    config_file = config_path.resolve()
    judge_dir = config.judge.prompts_dir if config.judge is not None else None
    prompts: set[str] = set()
    baselines: set[str] = set()
    notes: list[str] = []
    dataset_changed = config_changed = judge_changed = False

    for raw in changed_paths:
        name = raw.strip()
        if not name:
            continue
        path = (root / name).resolve()
        if path == config_file:
            config_changed = True
        elif _under(path, judge_dir):
            judge_changed = True
        elif _under(path, config.prompts_dir) and path.suffix in _PROMPT_SUFFIXES:
            if path.is_file():
                prompts.add(path.stem)
            else:
                notes.append(f"Prompt {path.stem} was deleted: nothing to evaluate for it.")
        elif _under(path, config.datasets_dir):
            dataset_changed = True
        elif _under(path, config.baselines_dir) and path.suffix == ".json":
            baselines.add(path.stem)

    if judge_changed:
        notes.append("The judge prompt changed. PR runs do not use the judge (cost).")
    if baseline in baselines:
        notes.append(
            f"Baseline '{baseline}' changed in this PR: reviewers, check why the reference moved."
        )
    plan = CiPlan(
        baseline=baseline,
        dataset_changed=dataset_changed,
        config_changed=config_changed,
        baselines_changed=tuple(sorted(baselines)),
        judge_changed=judge_changed,
    )

    def blocked(reason: str) -> CiPlan:
        return plan.model_copy(update={"blocking": reason, "notes": tuple(notes)})

    needs_reference = bool(prompts) or config_changed or dataset_changed or baseline in baselines
    if not needs_reference:
        return plan.model_copy(update={"notes": tuple(notes)})
    try:
        reference = load_baseline(config.baselines_dir, baseline)
    except DataValidationError as exc:
        return blocked(str(exc))
    if dataset_changed and baseline not in baselines:
        return blocked(
            f"The golden dataset changed but baseline '{baseline}' did not. Old and new answer "
            "keys cannot be compared: run the baseline prompt on the new dataset and promote "
            "it in this PR (docs/ci-setup.md)."
        )
    if not prompts:  # config, dataset or baseline changed: re-check the baseline's prompt
        prompts.add(reference.run.meta.prompt_version)
        notes.append(
            f"No prompt changed: re-evaluating the baseline's prompt "
            f"{reference.run.meta.prompt_version} against the new configuration."
        )
    if len(prompts) > MAX_PROMPTS:
        return blocked(
            f"{len(prompts)} prompt versions changed ({', '.join(sorted(prompts))}); at most "
            f"{MAX_PROMPTS} per PR fit the daily API quota. Split the PR."
        )
    return plan.model_copy(
        update={"prompt_versions": tuple(sorted(prompts)), "notes": tuple(notes)}
    )


@dataclass(frozen=True)
class PromptOutcome:
    version: str
    run: RunResult | None  # None: the run never produced a result (see the job log)
    comparison: Comparison | None
    reference: RunResult | None

    @property
    def verdict(self) -> Verdict:
        if self.run is None or self.run.status is RunStatus.ERROR or self.comparison is None:
            return Verdict.ERROR
        return self.comparison.verdict


def collect_outcomes(config: AppConfig, runs_dir: Path, plan: CiPlan) -> list[PromptOutcome]:
    """The newest run of each planned prompt in ``runs_dir`` and its saved comparison.

    In CI the runs directory starts empty, so "newest" is the run this job just made.
    """
    try:
        reference: RunResult | None = load_baseline(config.baselines_dir, plan.baseline).run
    except DataValidationError:
        reference = None
    runs = [r for r in list_runs(runs_dir) if r.meta.app == config.name]
    outcomes = []
    for version in plan.prompt_versions:
        run = next((r for r in runs if r.meta.prompt_version == version), None)
        comparison = None
        if run is not None:
            path = runs_dir / run.meta.run_id / f"comparison-{plan.baseline}.json"
            if path.is_file():
                comparison = Comparison.model_validate_json(path.read_text(encoding="utf-8"))
        outcomes.append(PromptOutcome(version, run, comparison, reference))
    return outcomes


def gate_verdict(plan: CiPlan, outcomes: list[PromptOutcome]) -> Verdict | None:
    """FAIL beats ERROR beats WARN beats PASS. None: nothing needed evaluating."""
    if plan.blocking is not None:
        return Verdict.FAIL
    if not plan.prompt_versions:
        return None
    verdicts = {o.verdict for o in outcomes}
    if len(outcomes) < len(plan.prompt_versions):
        verdicts.add(Verdict.ERROR)
    for verdict in (Verdict.FAIL, Verdict.ERROR, Verdict.WARN):
        if verdict in verdicts:
            return verdict
    return Verdict.PASS


def _demote(markdown: str) -> str:
    """Nest a run summary under the comment's top heading (## -> ###)."""
    return "\n".join("#" + line if line.startswith("##") else line for line in markdown.split("\n"))


def render_pr_comment(
    plan: CiPlan,
    outcomes: list[PromptOutcome],
    verdict: Verdict | None,
    *,
    details_url: str | None = None,
) -> str:
    lines = [COMMENT_MARKER]
    if verdict is None:
        lines += [
            "## ✅ RegressionGuard gate: nothing to evaluate",
            "",
            "Nothing in this PR needs a new evaluation (no prompt, golden dataset, baseline "
            "or `regguard.yaml` change).",
        ]
    else:
        lines += [f"## {_ICONS[verdict]} RegressionGuard gate: {verdict.value.upper()}", ""]
        if plan.blocking is not None:
            lines += [f"> **Blocked:** {md(plan.blocking)}", ""]
        if outcomes:
            lines += ["| Prompt | Verdict | Run |", "|---|---|---|"]
            for o in outcomes:
                run_id = f"`{md(o.run.meta.run_id)}`" if o.run else "no result"
                lines.append(
                    f"| `{md(o.version)}` | {_ICONS[o.verdict]} {o.verdict.value.upper()} "
                    f"| {run_id} |"
                )
        if verdict is Verdict.ERROR:
            lines += [
                "",
                "> **No quality verdict:** a run failed for technical reasons (provider "
                "outage, rate limit or budget). Re-run the failed job: answers already "
                "received are reused from the cache.",
            ]
    if plan.notes:
        lines += ["", *[f"- {md(note)}" for note in plan.notes]]
    if details_url:
        lines += ["", f"📄 Full HTML reports: [workflow run artifacts]({details_url})"]
    for o in outcomes:
        lines += ["", "---", ""]
        if o.run is None:
            lines.append(
                f"### 🛑 Prompt `{md(o.version)}`: no result "
                "(the run did not start; see the job log)"
            )
        else:
            lines.append(_demote(render_markdown(o.run, o.comparison, baseline=o.reference)))
    return "\n".join(lines).rstrip() + "\n"
