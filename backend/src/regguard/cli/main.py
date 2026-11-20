"""Command-line entrypoint. Thin shell: parse args, call services, format output, set exit code.

Exit codes: 0 ok (PASS, or WARN without --fail-on-warn), 1 output failed schema validation,
2 usage/config error, 3 provider error (run status ERROR), 4 regression gate failed.
"""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from regguard import __version__
from regguard.apps.config import AppConfig, load_app_config
from regguard.apps.registry import get_app
from regguard.core.config import Settings, load_settings
from regguard.core.errors import ComparisonError, ConfigError, DataValidationError, ProviderError
from regguard.core.logging import configure_logging
from regguard.core.types import (
    CaseChange,
    CaseResult,
    Comparison,
    DriftStatus,
    MetricDelta,
    MetricKind,
    RunResult,
    RunStatus,
    Severity,
    ThresholdLevel,
    Verdict,
)
from regguard.datasets.lint import dataset_stats, lint_dataset
from regguard.datasets.loader import list_versions
from regguard.datasets.models import Dataset
from regguard.evaluation.cache import CacheMode
from regguard.prompts.loader import discover_prompts, load_prompt_version
from regguard.providers.factory import build_provider
from regguard.services.compare_service import (
    compare_with_baseline,
    ensure_baseline_exists,
    promote_baseline,
)
from regguard.services.datasets import load_app_dataset
from regguard.services.drift_service import check_drift
from regguard.services.history_service import (
    HISTORY_ERRORS,
    import_runs,
    list_history,
    metric_trend,
    record_comparison,
    record_run,
    upgrade_database,
)
from regguard.services.invoke import InvokeResult, invoke_once
from regguard.services.run_service import (
    BudgetExceededError,
    RunOptions,
    check_budget,
    execute_prepared,
    git_sha,
    load_judge_prompt,
    mock_responder,
    prepare_run,
)
from regguard.storage.baseline_store import list_baselines, load_baseline
from regguard.storage.file_store import list_runs, load_run

EXIT_SCHEMA_INVALID = 1
EXIT_VALIDATION_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_PROVIDER_ERROR = 3
EXIT_GATE_FAILED = 4

app = typer.Typer(
    name="regguard",
    help="Detect regressions in LLM-powered applications.",
    no_args_is_help=True,
    add_completion=False,
)
prompt_app = typer.Typer(help="Inspect versioned prompts.", no_args_is_help=True)
app.add_typer(prompt_app, name="prompt")
dataset_app = typer.Typer(help="Validate and inspect golden datasets.", no_args_is_help=True)
app.add_typer(dataset_app, name="dataset")
runs_app = typer.Typer(help="Inspect stored evaluation runs.", no_args_is_help=True)
app.add_typer(runs_app, name="runs")
baseline_app = typer.Typer(help="Pin and inspect baselines.", no_args_is_help=True)
app.add_typer(baseline_app, name="baseline")
history_app = typer.Typer(help="Browse the run history database.", no_args_is_help=True)
app.add_typer(history_app, name="history")
db_app = typer.Typer(help="Manage the history database schema.", no_args_is_help=True)
app.add_typer(db_app, name="db")

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Path to the app's regguard.yaml.")
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"regguard {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """RegressionGuard command-line interface."""


def _fail(message: str, code: int) -> typer.Exit:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    return typer.Exit(code)


def _warn(message: str | None) -> None:
    if message:
        typer.secho(f"Warning: {message}", fg=typer.colors.YELLOW, err=True)


def _load_config(path: Path) -> AppConfig:
    try:
        return load_app_config(path)
    except ConfigError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc


@prompt_app.command("list")
def prompt_list(config: ConfigOption = Path("regguard.yaml")) -> None:
    """List prompt versions with their model and content hash."""
    cfg = _load_config(config)
    try:
        prompts = discover_prompts(cfg.prompts_dir)
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    if not prompts:
        typer.echo(f"No prompts found in {cfg.prompts_dir}")
        return
    for version, p in prompts.items():
        typer.echo(f"{version:<10} {p.id:<20} {p.model.model:<45} {p.content_hash[:19]}")


@prompt_app.command("show")
def prompt_show(version: str, config: ConfigOption = Path("regguard.yaml")) -> None:
    """Show one prompt version in full."""
    cfg = _load_config(config)
    try:
        p = load_prompt_version(cfg.prompts_dir, version)
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    typer.echo(f"id:        {p.id}\nversion:   {p.version}\nhash:      {p.content_hash}")
    typer.echo(f"model:     {p.model.model} (temperature={p.model.temperature})")
    typer.echo(f"few-shot:  {len(p.few_shot)} example(s)\n\n--- system ---\n{p.system}")
    typer.echo(f"\n--- user template ---\n{p.user_template}")


VersionOption = Annotated[
    str | None, typer.Option("--version", "-v", help="Dataset version (default: latest).")
]


def _load_dataset_or_exit(config: Path, version: str | None) -> tuple[Dataset, AppConfig]:
    cfg = _load_config(config)
    try:
        spec = get_app(cfg.app)
        return load_app_dataset(cfg, spec, version), cfg
    except ConfigError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_VALIDATION_FAILED) from exc


@dataset_app.command("list")
def dataset_list(config: ConfigOption = Path("regguard.yaml")) -> None:
    """List dataset versions."""
    cfg = _load_config(config)
    if cfg.datasets_dir is None:
        raise _fail("no datasets_dir in regguard.yaml", EXIT_CONFIG_ERROR)
    try:
        versions = list_versions(cfg.datasets_dir)
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    for version in versions:
        typer.echo(version)


@dataset_app.command("validate")
def dataset_validate(
    version: VersionOption = None,
    strict: Annotated[bool, typer.Option(help="Treat warnings as failures (use in CI).")] = False,
    min_cases: Annotated[int, typer.Option(help="Warn below this many cases.")] = 50,
    config: ConfigOption = Path("regguard.yaml"),
) -> None:
    """Validate a dataset: schema, ids, labels, plus privacy and quality warnings."""
    dataset, cfg = _load_dataset_or_exit(config, version)
    spec = get_app(cfg.app)
    findings = lint_dataset(
        dataset,
        label_field=spec.label_field,
        summary_field=spec.summary_field,
        min_cases=min_cases,
    )
    m = dataset.manifest
    typer.echo(f"{m.name}@{m.version}: {len(dataset.cases)} cases, {dataset.content_hash[:19]}")
    for f in findings:
        where = f"[{f.case_id}] " if f.case_id else ""
        typer.secho(f"  warning {f.code}: {where}{f.message}", fg=typer.colors.YELLOW)
    if findings and strict:
        raise _fail(f"{len(findings)} warning(s) in strict mode", EXIT_VALIDATION_FAILED)
    typer.secho(
        "OK" if not findings else f"OK with {len(findings)} warning(s)", fg=typer.colors.GREEN
    )


@dataset_app.command("stats")
def dataset_stats_cmd(
    version: VersionOption = None, config: ConfigOption = Path("regguard.yaml")
) -> None:
    """Show case counts by label, difficulty and tag."""
    dataset, cfg = _load_dataset_or_exit(config, version)
    stats = dataset_stats(dataset, label_field=get_app(cfg.app).label_field)
    typer.echo(f"{dataset.manifest.name}@{dataset.manifest.version}")
    for section, counts in stats.items():
        typer.echo(f"\n{section}:")
        for key, n in counts.items():
            typer.echo(f"  {key:<20} {n}")


@app.command("try")
def try_once(
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="Prompt version, e.g. v1.")],
    text: Annotated[str | None, typer.Option("--input", "-i", help="Input text.")] = None,
    input_file: Annotated[
        Path | None, typer.Option("--input-file", help="Read input text from a file.")
    ] = None,
    config: ConfigOption = Path("regguard.yaml"),
) -> None:
    """Run the app once on a single input and print the validated output."""
    if (text is None) == (input_file is None):
        raise _fail("provide exactly one of --input or --input-file", EXIT_CONFIG_ERROR)
    value = text if text is not None else input_file.read_text(encoding="utf-8")  # type: ignore[union-attr]

    try:
        settings = load_settings()
        configure_logging(settings.log_level, settings.log_format)
        cfg = load_app_config(config)
        spec = get_app(cfg.app)
        prompt_cfg = load_prompt_version(cfg.prompts_dir, prompt)
        if len(spec.input_variables) != 1:
            raise ConfigError("`try` supports single-input apps only")
        provider = build_provider(settings, mock_response=spec.mock_response)
    except (ConfigError, DataValidationError) as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc

    async def _run() -> InvokeResult:
        try:
            return await invoke_once(
                spec=spec,
                prompt=prompt_cfg,
                provider=provider,
                inputs={spec.input_variables[0]: value},
                model_override=settings.llm_model,
            )
        finally:
            await provider.aclose()

    try:
        result = asyncio.run(_run())
    except ProviderError as exc:
        raise _fail(f"provider call failed: {exc}", EXIT_PROVIDER_ERROR) from exc
    except ConfigError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc

    c = result.completion
    report = {
        "prompt": f"{prompt_cfg.id}@{prompt_cfg.version}",
        "prompt_hash": prompt_cfg.content_hash[:19],
        "provider": provider.name,
        "model": c.model,
        "schema_valid": result.schema_valid,
        "output": result.parsed,
        "validation_error": result.validation_error,
        "raw_output": None if result.schema_valid else c.text,
        "latency_ms": round(c.latency_ms, 1),
        "tokens": {"prompt": c.usage.prompt_tokens, "completion": c.usage.completion_tokens},
    }
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    if not result.schema_valid:
        raise typer.Exit(EXIT_SCHEMA_INVALID)


# --- evaluation runs ---------------------------------------------------------------------


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _judge_cell(r: CaseResult) -> str:
    if r.judge is None:
        return ""
    if r.judge.score is None:
        return "judge ERR"
    return f"judge {r.judge.score}/5"


def _case_row(r: CaseResult, labels: dict[str, str] | None = None) -> str:
    label = next((s for s in r.scores if s.name == "label_exact"), None)
    expected = (labels or {}).get(r.case_id) or (
        str(label.detail.get("expected", "")) if label else ""
    )
    actual = str(label.detail.get("actual", "")) if label else ""
    if r.error is not None:
        verdict, actual = "ERROR", r.error.type
    elif r.parsed_output is None:
        verdict, actual = "INVALID", "<schema>"
    else:
        verdict = "pass" if r.passed else "FAIL"
    latency = f"{r.latency_ms:.0f}ms" if r.latency_ms is not None else "-"
    cached = "cached" if r.cached else ""
    sample = f"#{r.sample_idx}" if r.sample_idx else ""
    return (
        f"  {r.case_id + sample:<16} {expected:<11} {actual:<14} {verdict:<8} {latency:>8} "
        f"{cached:<6} {_judge_cell(r)}"
    ).rstrip()


def _print_summary(result: RunResult) -> None:
    m, agg = result.meta, result.aggregates
    color = typer.colors.GREEN if result.status is RunStatus.COMPLETED else typer.colors.RED
    typer.secho(f"\nRun {m.run_id}: {result.status.value.upper()}", fg=color, bold=True)
    if result.error:
        typer.secho(f"  {result.error}", fg=typer.colors.RED)
    override = "  [MODEL OVERRIDE]" if m.model_override else ""
    typer.echo(f"  prompt  {m.prompt_version} ({m.prompt_hash[:19]})   model {m.model}{override}")
    typer.echo(f"  dataset {m.dataset_version} ({m.dataset_hash[:19]})   cases {len(result.cases)}")
    e = m.execution
    typer.echo(
        f"  calls   {e.api_calls} api, {e.cache_hits} cached, {e.retries} retries"
        f"   (cache: {e.cache_mode})"
    )
    if m.judge is not None:
        typer.echo(
            f"  judge   {e.judge_api_calls} api, {e.judge_cache_hits} cached, "
            f"{e.judge_retries} retries   {m.judge.get('model')} "
            f"(prompt {m.judge.get('prompt_version')})"
        )
    typer.echo("")
    for key in ("pass_rate", "schema_valid", "label_exact", "summary_format", "error_rate"):
        if key in agg:
            typer.echo(f"  {key:<24} {_pct(agg[key].value):>7}  (n={agg[key].n})")
    for key in sorted(k for k in agg if k.startswith("label_exact/")):
        typer.echo(f"  {key:<24} {_pct(agg[key].value):>7}  (n={agg[key].n})")
    for key in ("macro_f1", "summary_similarity"):
        if key in agg:
            typer.echo(f"  {key:<24} {agg[key].value:>7.2f}  (n={agg[key].n})")
    if "summary_judge" in agg:
        judge = agg["summary_judge"]
        typer.echo(f"  {'summary_judge':<24} {judge.value:>7.2f}  (n={judge.n}, scale 1-5)")
    if "judge_error_rate" in agg and agg["judge_error_rate"].value > 0:
        errors = agg["judge_error_rate"]
        typer.secho(
            f"  {'judge_error_rate':<24} {_pct(errors.value):>7}  (n={errors.n})",
            fg=typer.colors.YELLOW,
        )
    for key in ("latency_ms_p50", "latency_ms_p95"):
        if key in agg:
            typer.echo(f"  {key:<24} {agg[key].value:>7.0f}  (n={agg[key].n}, fresh calls)")
    if "tokens_total" in agg:
        typer.echo(f"  {'tokens_total':<24} {agg['tokens_total'].value:>7.0f}")


FailOnWarnOption = Annotated[
    bool, typer.Option("--fail-on-warn", help="Exit with code 4 on WARN too, not only on FAIL.")
]
AllowDatasetChangeOption = Annotated[
    bool,
    typer.Option(
        "--allow-dataset-change",
        help="Compare even if the dataset changed (shared cases only, with a warning).",
    ),
]


@app.command("run")
def run(
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="Prompt version, e.g. v1.")],
    dataset_version: Annotated[
        str | None, typer.Option("--dataset-version", help="Default: latest.")
    ] = None,
    limit: Annotated[
        int | None, typer.Option(help="Run a label-stratified subset of N cases.")
    ] = None,
    ids: Annotated[list[str] | None, typer.Option("--id", help="Only these case ids.")] = None,
    tags: Annotated[list[str] | None, typer.Option("--tag", help="Only cases with a tag.")] = None,
    seed: Annotated[int, typer.Option(help="Seed for the stratified subset.")] = 0,
    samples: Annotated[int, typer.Option(min=1, help="Calls per case (flakiness).")] = 1,
    cache: Annotated[CacheMode, typer.Option(help="Response cache mode.")] = CacheMode.READ_WRITE,
    max_requests: Annotated[
        int, typer.Option(help="Refuse runs needing more API calls than this.")
    ] = 50,
    baseline: Annotated[
        str | None, typer.Option("--baseline", "-b", help="Compare with this baseline afterwards.")
    ] = None,
    fail_on_warn: FailOnWarnOption = False,
    allow_dataset_change: AllowDatasetChangeOption = False,
    judge: Annotated[
        bool, typer.Option("--judge/--no-judge", help="Grade summaries with the LLM judge.")
    ] = True,
    config: ConfigOption = Path("regguard.yaml"),
) -> None:
    """Evaluate a prompt version against the golden dataset and save the result."""
    options = RunOptions(
        prompt_version=prompt,
        dataset_version=dataset_version,
        limit=limit,
        ids=ids or (),
        tags=tags or (),
        seed=seed,
        n_samples=samples,
        cache_mode=cache,
        max_requests=max_requests,
        judge=judge,
    )
    try:
        settings = load_settings()
        configure_logging(settings.log_level, settings.log_format)
        cfg = load_app_config(config)
        spec = get_app(cfg.app)
        judge_prompt = load_judge_prompt(cfg, spec) if judge else None
        provider = build_provider(settings, mock_response=mock_responder(spec, judge_prompt))
        prepared = prepare_run(cfg, options, settings, provider_name=provider.name)
        plan = prepared.plan
        app_cached = plan.total_calls - (prepared.uncached_calls - prepared.uncached_judge_calls)
        typer.echo(
            f"Planned: {plan.prompt.id}@{plan.prompt.version} on "
            f"{plan.dataset.manifest.name}@{plan.dataset.manifest.version}: "
            f"{len(plan.cases)} case(s) x {plan.n_samples} sample(s) = {plan.total_calls} call(s), "
            f"{app_cached} cached. Model: {plan.model}"
        )
        if prepared.judge_prompt is not None:
            typer.echo(
                f"Judge:   up to {prepared.judge_calls} call(s), "
                f"{prepared.judge_calls - prepared.uncached_judge_calls} cached. "
                f"Model: {prepared.judge_prompt.model.model}"
            )
        typer.echo(
            f"Budget:  {prepared.uncached_calls} API call(s) needed, "
            f"hard cap {options.max_requests} including retries (--max-requests)"
        )
        check_budget(prepared)
        if baseline is not None:
            ensure_baseline_exists(cfg, baseline)  # fail before spending any API call
    except (ConfigError, DataValidationError, BudgetExceededError) as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc

    def progress(done: int, total: int) -> None:
        typer.echo(f"\r  {done}/{total} done", nl=False)

    result = asyncio.run(
        execute_prepared(
            prepared,
            provider,
            settings,
            git_revision=git_sha(cfg.prompts_dir),
            on_progress=progress,
        )
    )
    typer.echo("")
    for case_result in result.cases:
        typer.echo(_case_row(case_result, result.meta.case_labels))
    _print_summary(result)
    typer.echo(f"\nSaved: {settings.runs_dir / result.meta.run_id / 'result.json'}")
    _warn(record_run(settings, result))
    if result.status is RunStatus.ERROR:
        if baseline is not None:
            typer.secho("Comparison skipped: the run itself failed.", fg=typer.colors.RED)
        raise typer.Exit(EXIT_PROVIDER_ERROR)
    if baseline is not None:
        _compare_and_exit(
            cfg,
            settings,
            result,
            baseline_name=baseline,
            against_run=None,
            allow_dataset_change=allow_dataset_change,
            fail_on_warn=fail_on_warn,
            show_all=False,
        )


@runs_app.command("list")
def runs_list(
    limit: Annotated[int, typer.Option(help="Show at most N runs.")] = 20,
) -> None:
    """List stored runs, newest first."""
    settings = load_settings()
    results = list_runs(settings.runs_dir)[:limit]
    if not results:
        typer.echo(f"No runs in {settings.runs_dir}")
        return
    for r in results:
        m = r.meta
        pass_rate = _pct(r.aggregates["pass_rate"].value) if "pass_rate" in r.aggregates else "-"
        typer.echo(
            f"{m.run_id:<24} {m.prompt_version:<6} {m.dataset_version:<6} {len(r.cases):>4} cases "
            f"{pass_rate:>7}  {r.status.value:<9} {m.model}"
        )


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="Run id or unique prefix.")],
    all_cases: Annotated[bool, typer.Option("--all", help="Show passing cases too.")] = False,
) -> None:
    """Show a stored run: summary and failing cases with raw outputs."""
    settings = load_settings()
    try:
        result = load_run(settings.runs_dir, run_id)
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc

    def low_judge(c: CaseResult) -> bool:
        return c.judge is not None and (c.judge.score is None or c.judge.score <= 3)

    shown = [c for c in result.cases if all_cases or not c.passed or low_judge(c)]
    for c in shown:
        typer.echo(_case_row(c, result.meta.case_labels))
        if not c.passed:
            detail = c.error.message if c.error else (c.raw_output or "")
            typer.echo(f"      {detail[:300]}")
        if c.judge is not None:
            summary = (c.parsed_output or {}).get("summary", "")
            note = c.judge.error.message if c.judge.error else c.judge.reason
            typer.echo(f"      summary: {str(summary)[:200]}")
            typer.echo(f"      judge:   {note[:300]}")
    _print_summary(result)


# --- baselines and comparison ------------------------------------------------------------

_VERDICT_COLORS = {
    Verdict.PASS: typer.colors.GREEN,
    Verdict.WARN: typer.colors.YELLOW,
    Verdict.FAIL: typer.colors.RED,
    Verdict.ERROR: typer.colors.RED,
}
_SEVERITY_COLORS = {
    Severity.FAIL: typer.colors.RED,
    Severity.WARN: typer.colors.YELLOW,
    Severity.INFO: None,
}


def _fmt_metric_value(value: float, kind: MetricKind) -> str:
    if kind is MetricKind.RATE:
        return _pct(value)
    return f"{value:.2f}" if abs(value) < 10 else f"{value:.0f}"


def _metric_row(m: MetricDelta) -> str:
    is_rate = m.regressed is not None
    base = _fmt_metric_value(m.baseline, m.kind)
    cand = _fmt_metric_value(m.candidate, m.kind)
    if m.delta is None:
        delta = "n/a"
    elif m.unit == "absolute":
        delta = f"{m.delta * 100:+.1f} pts"
    else:
        delta = f"{m.delta * 100:+.0f}%"
    flips = f"{m.regressed}/{m.improved}" if is_rate else "-"
    p_value = f"{m.p_value:.3f}" if m.p_value is not None else "-"
    level = "" if m.level is ThresholdLevel.OK else m.level.value.upper()
    if level and not m.gating:
        level += " (info)"
    cells = f"{base:>8} {cand:>9} {delta:>10} {flips:>7} {p_value:>7} {m.n:>4}"
    return f"  {m.metric:<24} {cells}  {level}"


def _print_comparison(c: Comparison, *, show_all: bool) -> None:
    against = f"baseline '{c.baseline_name}'" if c.baseline_name else "run"
    typer.echo(f"\nComparison: {c.candidate_run_id} vs {against} ({c.baseline_run_id})")
    for r in c.reasons:
        color = _SEVERITY_COLORS[r.severity]
        typer.secho(f"  {r.severity.value.upper():<5} {r.code:<24} {r.message}", fg=color)
    if c.metrics:
        typer.echo(
            f"\n  {'metric':<24} {'baseline':>8} {'candidate':>9} {'delta':>10} {'-/+':>7} "
            f"{'p':>7} {'n':>4}  level"
        )
        for m in c.metrics:
            typer.echo(_metric_row(m))
    if c.counts:
        summary = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in sorted(c.counts.items()))
        typer.echo(f"\n  cases: {summary}")
    for d in c.cases:
        interesting = d.change in (CaseChange.REGRESSED, CaseChange.IMPROVED, CaseChange.SKIPPED)
        if not (show_all or interesting):
            continue
        failing = ", ".join(d.candidate_failed_metrics) or "-"
        flag = "  [CRITICAL CASE]" if d.critical else ""
        typer.echo(
            f"  {d.change.value.upper():<10} {d.case_id:<14} {d.label or '':<10} "
            f"now failing: {failing}{flag}"
        )
    typer.secho(f"\nVERDICT: {c.verdict.value.upper()}", fg=_VERDICT_COLORS[c.verdict], bold=True)


def _compare_and_exit(
    cfg: AppConfig,
    settings: Settings,
    candidate: RunResult,
    *,
    baseline_name: str | None,
    against_run: str | None,
    allow_dataset_change: bool,
    fail_on_warn: bool,
    show_all: bool,
) -> None:
    try:
        comparison, path = compare_with_baseline(
            cfg,
            settings.runs_dir,
            candidate,
            baseline_name=baseline_name,
            against_run=against_run,
            allow_dataset_change=allow_dataset_change,
        )
    except (ComparisonError, DataValidationError) as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    _print_comparison(comparison, show_all=show_all)
    typer.echo(f"Saved: {path}")
    _warn(record_comparison(settings, comparison, candidate))
    if comparison.verdict is Verdict.ERROR:
        raise typer.Exit(EXIT_PROVIDER_ERROR)
    if comparison.verdict is Verdict.FAIL or (fail_on_warn and comparison.verdict is Verdict.WARN):
        raise typer.Exit(EXIT_GATE_FAILED)


@app.command("compare")
def compare_cmd(
    candidate: Annotated[str, typer.Argument(help="Candidate run id or unique prefix.")],
    baseline: Annotated[
        str, typer.Option("--baseline", "-b", help="Baseline name to compare against.")
    ] = "main",
    against: Annotated[
        str | None, typer.Option("--against", help="Compare with this run id instead.")
    ] = None,
    fail_on_warn: FailOnWarnOption = False,
    allow_dataset_change: AllowDatasetChangeOption = False,
    all_cases: Annotated[bool, typer.Option("--all", help="List unchanged cases too.")] = False,
    config: ConfigOption = Path("regguard.yaml"),
) -> None:
    """Compare a stored run with a baseline and print the PASS / WARN / FAIL verdict."""
    settings = load_settings()
    cfg = _load_config(config)
    try:
        result = load_run(settings.runs_dir, candidate)
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    _compare_and_exit(
        cfg,
        settings,
        result,
        baseline_name=baseline,
        against_run=against,
        allow_dataset_change=allow_dataset_change,
        fail_on_warn=fail_on_warn,
        show_all=all_cases,
    )


@baseline_app.command("promote")
def baseline_promote(
    run_id: Annotated[str, typer.Argument(help="Run id or unique prefix to pin.")],
    name: Annotated[str, typer.Option("--name", "-n", help="Baseline name.")] = "main",
    replace: Annotated[bool, typer.Option(help="Overwrite an existing baseline.")] = False,
    note: Annotated[str, typer.Option(help="Why this run is trusted.")] = "",
    config: ConfigOption = Path("regguard.yaml"),
) -> None:
    """Pin a completed run as a baseline file (commit it so CI can compare against it)."""
    settings = load_settings()
    cfg = _load_config(config)
    try:
        baseline, path = promote_baseline(
            cfg,
            settings.runs_dir,
            run_id,
            name=name,
            replace=replace,
            note=note,
            git_revision=git_sha(cfg.prompts_dir),
        )
    except (ComparisonError, DataValidationError) as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    m = baseline.run.meta
    typer.secho(f"Baseline '{name}' <- run {m.run_id}", fg=typer.colors.GREEN)
    typer.echo(
        f"  prompt {m.prompt_version}, dataset {m.dataset_version}, {len(baseline.run.cases)} cases"
    )
    typer.echo(f"Saved: {path}\nCommit this file so CI compares against it.")


@baseline_app.command("list")
def baseline_list(config: ConfigOption = Path("regguard.yaml")) -> None:
    """List baselines for this app."""
    cfg = _load_config(config)
    try:
        baselines = list_baselines(cfg.baselines_dir)
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    if not baselines:
        typer.echo(f"No baselines in {cfg.baselines_dir}")
        return
    for b in baselines:
        h, m = b.header, b.run.meta
        typer.echo(
            f"{h.name:<12} run {h.source_run_id:<24} prompt {m.prompt_version:<6} "
            f"dataset {m.dataset_version:<6} {len(b.run.cases):>4} cases  "
            f"promoted {h.promoted_at:%Y-%m-%d %H:%M}"
        )


@baseline_app.command("show")
def baseline_show(
    name: Annotated[str, typer.Argument(help="Baseline name.")] = "main",
    config: ConfigOption = Path("regguard.yaml"),
) -> None:
    """Show a baseline's provenance and scores."""
    cfg = _load_config(config)
    try:
        b = load_baseline(cfg.baselines_dir, name)
    except DataValidationError as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    h = b.header
    typer.echo(f"Baseline '{h.name}' (promoted {h.promoted_at:%Y-%m-%d %H:%M} UTC)")
    typer.echo(f"  source run {h.source_run_id}   git {h.git_sha or '-'}")
    if h.note:
        typer.echo(f"  note: {h.note}")
    _print_summary(b.run)


# --- history and drift ---------------------------------------------------------------------

_HISTORY_ERRORS = HISTORY_ERRORS
AppFilterOption = Annotated[
    str | None, typer.Option("--app", help="Only runs of this app (regguard.yaml `name`).")
]


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Create or upgrade the history database schema (needed for PostgreSQL)."""
    settings = load_settings()
    try:
        before, after = upgrade_database(settings)
    except _HISTORY_ERRORS as exc:
        raise _fail(f"database upgrade failed: {exc}", EXIT_CONFIG_ERROR) from exc
    if before == after:
        typer.echo(f"Database already at revision {after}.")
    else:
        typer.secho(f"Database upgraded: {before or 'empty'} -> {after}", fg=typer.colors.GREEN)


@history_app.command("import")
def history_import() -> None:
    """Add existing run files (runs/*/result.json) to the history database. Safe to repeat."""
    settings = load_settings()
    try:
        summary = import_runs(settings)
    except _HISTORY_ERRORS as exc:
        raise _fail(f"import failed: {exc}", EXIT_CONFIG_ERROR) from exc
    typer.echo(
        f"Imported {summary.imported} run(s), {summary.skipped} already present, "
        f"{summary.comparisons} comparison(s)."
    )
    for failure in summary.failed:
        typer.secho(f"  skipped unreadable file: {failure}", fg=typer.colors.YELLOW)


@history_app.command("list")
def history_list(
    app_name: AppFilterOption = None,
    limit: Annotated[int, typer.Option(help="Show at most N runs.")] = 20,
) -> None:
    """Runs in the history database, newest first."""
    settings = load_settings()
    try:
        records = list_history(settings, app=app_name, limit=limit)
    except _HISTORY_ERRORS as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    if not records:
        typer.echo("No runs in history yet. Run an evaluation, or: regguard history import")
        return
    for r in records:
        fresh = "fresh" if r.cache_hits == 0 and r.api_calls > 0 else f"{r.cache_hits} cached"
        typer.echo(
            f"{r.run_id:<24} {r.started_at:%Y-%m-%d %H:%M}  {r.prompt_version:<6} "
            f"{r.dataset_version:<6} {r.n_cases:>4} cases  {r.status:<9} {r.trigger:<8} "
            f"{fresh:<10} {r.model}"
        )


@history_app.command("trend")
def history_trend(
    metric: Annotated[str, typer.Option("--metric", "-m", help="e.g. label_exact")],
    app_name: AppFilterOption = None,
    limit: Annotated[int, typer.Option(help="Last N runs.")] = 20,
) -> None:
    """One metric over the most recent runs, oldest first."""
    settings = load_settings()
    try:
        series = metric_trend(settings, metric, app=app_name, limit=limit)
    except _HISTORY_ERRORS as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    if not series:
        typer.echo(f"No values for metric '{metric}' in history.")
        return
    top = max(abs(v) for _, v in series) or 1.0
    for record, value in series:
        bar = "#" * round(20 * abs(value) / top)
        typer.echo(f"{record.run_id:<24} {record.prompt_version:<6} {value:>9.3f}  {bar}")


@app.command("drift")
def drift_cmd(
    baseline: Annotated[
        str, typer.Option("--baseline", "-b", help="Baseline whose values are the reference.")
    ] = "main",
    fail_on_drift: Annotated[
        bool, typer.Option("--fail-on-drift", help="Exit with code 4 when drift is detected.")
    ] = False,
    config: ConfigOption = Path("regguard.yaml"),
) -> None:
    """Check the run history for drift against a baseline (for scheduled monitoring runs)."""
    settings = load_settings()
    cfg = _load_config(config)
    try:
        report = check_drift(cfg, settings, baseline_name=baseline)
    except (DataValidationError, *_HISTORY_ERRORS) as exc:
        raise _fail(str(exc), EXIT_CONFIG_ERROR) from exc
    d = cfg.gate.drift
    typer.echo(
        f"Drift: {report.app} vs baseline '{baseline}' ({report.baseline_run_id})\n"
        f"  {report.comparable_runs} comparable run(s), {report.fresh_runs} fresh; "
        f"window {d.window}, alert after {d.consecutive} consecutive worse run(s)"
    )
    for note in report.notes:
        typer.secho(f"  note: {note}", fg=typer.colors.YELLOW)
    colors = {
        DriftStatus.OK: typer.colors.GREEN,
        DriftStatus.DRIFT: typer.colors.RED,
        DriftStatus.INSUFFICIENT: typer.colors.YELLOW,
    }
    for m in report.metrics:
        flag = "  [NEW EPISODE]" if m.new_episode else ""
        typer.secho(
            f"  {m.status.value.upper():<12} {m.metric:<20} {m.message}{flag}",
            fg=colors[m.status],
        )
    typer.secho(
        f"\nDRIFT STATUS: {report.status.value.upper()}", fg=colors[report.status], bold=True
    )
    if report.status is DriftStatus.INSUFFICIENT:
        typer.echo(
            "Monitoring needs fresh runs of the same prompt over time, e.g. daily:\n"
            "  regguard run -p <version> --limit <N> --cache refresh"
        )
    if fail_on_drift and report.status is DriftStatus.DRIFT:
        raise typer.Exit(EXIT_GATE_FAILED)
