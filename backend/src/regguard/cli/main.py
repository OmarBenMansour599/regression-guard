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
from regguard.prompts.loader import discover_prompts, load_prompt_version
from regguard.providers.factory import build_provider
from regguard.services.invoke import InvokeResult, invoke_once

EXIT_SCHEMA_INVALID = 1
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
