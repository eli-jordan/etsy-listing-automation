"""Explicit global model installation commands; no server or workspace queue."""

from __future__ import annotations

import json
from dataclasses import asdict

import typer

from etsy_listings.core.preparation.runtime import Capability, Runtime, SetupError

app = typer.Typer(
    no_args_is_help=True, help="Install and inspect the native Windows Marigold worker."
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


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", help="Return the capability report as JSON."),
) -> None:
    """Inspect installation, pinned weights and CUDA. Never download or install."""
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
def setup(json_output: bool = typer.Option(False, "--json")) -> None:
    """Explicitly install locked dependencies and verified weights, then run smoke inference."""
    _install(update=False, as_json=json_output)


@app.command()
def update(json_output: bool = typer.Option(False, "--json")) -> None:
    """Verify and select the required engine, retaining previously installed versions."""
    _install(update=True, as_json=json_output)
