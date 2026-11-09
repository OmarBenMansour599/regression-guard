"""Command-line entrypoint. Commands are added phase by phase."""

import typer

from regguard import __version__

app = typer.Typer(
    name="regguard",
    help="Detect regressions in LLM-powered applications.",
    no_args_is_help=True,
    add_completion=False,
)


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
