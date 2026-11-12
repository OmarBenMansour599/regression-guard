"""Command-line entrypoint. Thin shell: parse args, call services, format output, set exit code.

Exit codes: 0 ok, 1 output failed schema validation, 2 usage/config error, 3 provider error.
"""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from regguard import __version__
from regguard.apps.config import AppConfig, load_app_config
from regguard.apps.registry import get_app
from regguard.core.config import load_settings
from regguard.core.errors import ConfigError, DataValidationError, ProviderError
from regguard.core.logging import configure_logging
from regguard.core.types import CaseResult, RunResult, RunStatus
from regguard.datasets.lint import dataset_stats, lint_dataset
from regguard.datasets.loader import list_versions
from regguard.datasets.models import Dataset
from regguard.evaluation.cache import CacheMode
from regguard.prompts.loader import discover_prompts, load_prompt_version
from regguard.providers.factory import build_provider
from regguard.services.datasets import load_app_dataset
from regguard.services.invoke import InvokeResult, invoke_once
from regguard.services.run_service import (
    BudgetExceededError,
    RunOptions,
    check_budget,
    execute_prepared,
    git_sha,
    prepare_run,
)
from regguard.storage.file_store import list_runs, load_run

EXIT_SCHEMA_INVALID = 1
EXIT_VALIDATION_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_PROVIDER_ERROR = 3

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


def _case_row(r: CaseResult) -> str:
    label = next((s for s in r.scores if s.name == "label_exact"), None)
    expected = str(label.detail.get("expected", "")) if label else ""
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
        f"  {r.case_id + sample:<16} {expected:<11} {actual:<14} {verdict:<8} {latency:>8} {cached}"
    )


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
    typer.echo("")
    for key in ("pass_rate", "schema_valid", "label_exact", "error_rate"):
        if key in agg:
            typer.echo(f"  {key:<24} {_pct(agg[key].value):>7}  (n={agg[key].n})")
    for key in sorted(k for k in agg if k.startswith("label_exact/")):
        typer.echo(f"  {key:<24} {_pct(agg[key].value):>7}  (n={agg[key].n})")
    for key in ("latency_ms_p50", "latency_ms_p95"):
        if key in agg:
            typer.echo(f"  {key:<24} {agg[key].value:>7.0f}  (n={agg[key].n}, fresh calls)")
    if "tokens_total" in agg:
        typer.echo(f"  {'tokens_total':<24} {agg['tokens_total'].value:>7.0f}")


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
    )
    try:
        settings = load_settings()
        configure_logging(settings.log_level, settings.log_format)
        cfg = load_app_config(config)
        provider = build_provider(settings, mock_response=get_app(cfg.app).mock_response)
        prepared = prepare_run(cfg, options, settings, provider_name=provider.name)
        plan = prepared.plan
        typer.echo(
            f"Planned: {plan.prompt.id}@{plan.prompt.version} on "
            f"{plan.dataset.manifest.name}@{plan.dataset.manifest.version}: "
            f"{len(plan.cases)} case(s) x {plan.n_samples} sample(s) = {plan.total_calls} call(s), "
            f"{plan.total_calls - prepared.uncached_calls} cached. Model: {plan.model}"
        )
        check_budget(prepared)
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
        typer.echo(_case_row(case_result))
    _print_summary(result)
    typer.echo(f"\nSaved: {settings.runs_dir / result.meta.run_id / 'result.json'}")
    if result.status is RunStatus.ERROR:
        raise typer.Exit(EXIT_PROVIDER_ERROR)


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
    shown = [c for c in result.cases if all_cases or not c.passed]
    for c in shown:
        typer.echo(_case_row(c))
        if not c.passed:
            detail = c.error.message if c.error else (c.raw_output or "")
            typer.echo(f"      {detail[:300]}")
    _print_summary(result)
