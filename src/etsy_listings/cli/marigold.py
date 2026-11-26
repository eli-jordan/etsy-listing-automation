from __future__ import annotations

import json
from dataclasses import asdict
from typing import Annotated

import typer

from etsy_listings.core.preparation.runtime import Capability, Runtime, SetupError

app = typer.Typer(
    no_args_is_help=True,
    help="Install and check Marigold, the Windows GPU worker that prepares templates.",
)


def _show(report: Capability, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(asdict(report), indent=2))
    elif report.available:
        typer.echo(f"Marigold engine {report.engine_version} is available.")
        if report.details:
            typer.echo(f"GPU: {report.details.get('gpu', 'CUDA available')}")
        if report.update_available:
            typer.echo(
                f"Engine {report.required_engine} is available. Run etsy-listings marigold update."
            )
    else:
        typer.echo(report.problem)


JsonOption = Annotated[bool, typer.Option("--json", help="Print the report as JSON.")]


@app.command()
def status(*, json_output: JsonOption = False) -> None:
    """Report whether the worker, its model weights and CUDA are ready.

    Installs nothing. Uses the last full check unless a file has changed since; setup and
    update always check every file."""
    _show(Runtime().inspect(), as_json=json_output)


def _install(*, update: bool, as_json: bool) -> None:
    typer.echo(
        "Verifying the isolated worker, pinned weights and normals/lighting/depth inference.",
        err=True,
    )
    try:
        runtime = Runtime()
        report = runtime.update() if update else runtime.setup()
    except SetupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    _show(report, as_json=as_json)


@app.command()
def setup(*, json_output: JsonOption = False) -> None:
    """Install the worker and its model weights, then test it."""
    _install(update=False, as_json=json_output)


@app.command()
def update(*, json_output: JsonOption = False) -> None:
    """Install the engine version this release needs, keeping older ones."""
    _install(update=True, as_json=json_output)
