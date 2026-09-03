"""Typer CLI. One module per command; this module wires them into one app.

``plan``, ``apply`` and ``ui`` exist as of Phase 1 -- ``new``, ``auth``,
``catalog refresh``, ``unlock`` and ``status`` are built in later phases, per
A10's strict phase order.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import typer

from etsy_listings import __about__
from etsy_listings.catalog.cache import CachedCatalogClient
from etsy_listings.catalog.http import HttpCatalogClient
from etsy_listings.cli.render import format_plan
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.workspace.userpath import to_native_path
from etsy_listings.workspace.workspace import Workspace, WorkspaceNotFoundError

app = typer.Typer(no_args_is_help=True)


@app.callback()
def _root_callback() -> None:
    """Etsy print-on-demand listing automation."""
    # A no-op callback keeps `plan` addressed as a subcommand (`etsy-listings
    # plan ...`) even while it's the app's only command -- Typer otherwise
    # collapses a single-command app so its command name is invisible, which
    # would silently change the CLI surface again the moment a second command
    # (`apply`, `new`, ...) is added in a later phase.


def _open_workspace(root: str | None) -> Workspace:
    """``--root`` is taken as a raw string, not a Path, so a Cygwin-style
    ``/home/...`` argument can be translated before pathlib mangles it."""
    try:
        return Workspace.discover(root_override=to_native_path(root) if root else None)
    except WorkspaceNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _run_context(workspace: Workspace, on_event: EventSink | None = None) -> RunContext:
    catalog = CachedCatalogClient(HttpCatalogClient(), workspace.catalog_cache_dir())
    if on_event is None:
        return RunContext(workspace=workspace, catalog=catalog)
    return RunContext(workspace=workspace, catalog=catalog, on_event=on_event)


def _empty_lock() -> Lockfile:
    return Lockfile.empty(tool_version=__about__.VERSION, applied_at=datetime.now(UTC).isoformat())


def _validate_config(workspace: Workspace, listing: str) -> None:
    """Parse everything the run depends on, so a config error is reported
    before any stage work starts. The parsed values are discarded -- each stage
    loads what it needs itself (A1); this is purely the early failure."""
    config = workspace.load_listing(listing)
    workspace.load_profile(config.profile)
    workspace.load_exceptions()


def _target_listings(workspace: Workspace, listing: str | None, every: bool) -> list[str]:
    if not listing and not every:
        typer.echo("pass a listing name or --all", err=True)
        raise typer.Exit(code=1)

    names = workspace.listing_names() if every else [listing] if listing else []
    if not names:
        typer.echo("no listings found" if every else f"no such listing: {listing}", err=True)
        raise typer.Exit(code=1)
    return names


def _run_over_listings(
    workspace: Workspace,
    names: list[str],
    ctx: RunContext,
    action: Callable[[RunContext, str, Lockfile], None],
) -> None:
    """Run ``action`` per listing, continue-on-error (PRD 16: one bad listing
    must not halt fifty good ones), exiting non-zero if any failed."""
    failed = False
    for name in names:
        try:
            _validate_config(workspace, name)
        except ConfigLoadError as exc:
            typer.echo(str(exc), err=True)
            failed = True
            continue
        action(ctx, name, Lockfile.read(workspace.lock_file(name)) or _empty_lock())

    raise typer.Exit(code=1 if failed else 0)


@app.command()
def plan(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike"),
    all: bool = typer.Option(False, "--all", help="Plan every listing in the workspace"),
    root: str | None = typer.Option(None, "--root", help="Workspace root override"),
) -> None:
    """Three-way diff against live state; decides which stages need to run."""
    workspace = _open_workspace(root)
    ctx = _run_context(workspace)

    def show_plan(ctx: RunContext, name: str, lock: Lockfile) -> None:
        typer.echo(format_plan(build_plan(ctx, name, lock, STAGES)))
        typer.echo("")

    _run_over_listings(workspace, _target_listings(workspace, listing, all), ctx, show_plan)


@app.command()
def apply(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike"),
    all: bool = typer.Option(False, "--all", help="Apply every listing in the workspace"),
    root: str | None = typer.Option(None, "--root", help="Workspace root override"),
) -> None:
    """Execute every stage the plan identified. Only local stages (render) run
    until later phases add Printify/Etsy."""
    workspace = _open_workspace(root)
    ctx = _run_context(workspace, on_event=lambda msg: typer.echo(f"  {msg}"))

    def run_apply(ctx: RunContext, name: str, lock: Lockfile) -> None:
        typer.echo(f"applying {name}")
        plan = build_plan(ctx, name, lock, STAGES)
        execute(ctx, plan, lock, STAGES).write(workspace.lock_file(name))

    _run_over_listings(workspace, _target_listings(workspace, listing, all), ctx, run_apply)


@app.command()
def new(
    design: str = typer.Argument(..., help="Design name, matching designs/<name>.png"),
    category: str = typer.Option("tshirt", "--category", help="Blueprint category filter"),
    root: str | None = typer.Option(None, "--root", help="Workspace root override"),
) -> None:
    """Interactive garment/provider picker; writes profile (if absent) + listing."""
    from etsy_listings.newcmd.interactive import run_new

    workspace = _open_workspace(root)
    catalog = CachedCatalogClient(HttpCatalogClient(), workspace.catalog_cache_dir())
    run_new(workspace, catalog, design, category)


@app.command()
def ui(
    root: str | None = typer.Option(None, "--root", help="Workspace root override"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Serve the calibrator (Phase 1). The dashboard/setup wizard/run runner
    described in the PRD's ``## UI`` section land in Phase 5."""
    import uvicorn

    from etsy_listings.ui.api.app import create_app

    workspace = _open_workspace(root)
    uvicorn.run(create_app(workspace), host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
