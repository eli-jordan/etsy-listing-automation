"""Typer CLI. One module per command; this module wires them into one app.

``plan``, ``apply`` and ``ui`` exist as of Phase 1 -- ``new``, ``auth``,
``catalog refresh``, ``unlock`` and ``status`` are built in later phases, per
A10's strict phase order.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from etsy_listings import __about__
from etsy_listings.catalog.cache import CachedCatalogClient
from etsy_listings.catalog.http import HttpCatalogClient
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.exceptions import load_exceptions
from etsy_listings.config.listing import Listing
from etsy_listings.config.profile import Profile
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan, format_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.workspace.layout import LISTINGS_DIR
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


def _listing_names(workspace: Workspace) -> list[str]:
    listings_dir = workspace.root / LISTINGS_DIR
    if not listings_dir.is_dir():
        return []
    return sorted(p.name for p in listings_dir.iterdir() if (p / "listing.yaml").is_file())


def _lock_path(workspace: Workspace, name: str) -> Path:
    return workspace.root / LISTINGS_DIR / name / "state.lock.json"


def _read_or_empty_lock(path: Path) -> Lockfile:
    return Lockfile.read(path) or Lockfile.empty(
        tool_version=__about__.VERSION, applied_at=datetime.now(UTC).isoformat()
    )


def _load_listing(workspace: Workspace, name: str) -> Listing:
    listing_dir = workspace.root / LISTINGS_DIR / name
    listing_path = listing_dir / "listing.yaml"
    listing = Listing.load(listing_path, currency=workspace.defaults.currency)

    profile_path = workspace.root / "profiles" / f"{listing.profile}.yaml"
    Profile.load(profile_path)  # validated for side effect of catching config errors early

    exceptions_path = workspace.root / "exceptions.yaml"
    load_exceptions(exceptions_path)  # validated eagerly; used by render/new in later phases

    return listing


@app.command()
def plan(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike"),
    all: bool = typer.Option(False, "--all", help="Plan every listing in the workspace"),
    root: str | None = typer.Option(None, "--root", help="Workspace root override"),
) -> None:
    """Three-way diff against live state; decides which stages need to run."""
    if not listing and not all:
        typer.echo("pass a listing name or --all", err=True)
        raise typer.Exit(code=1)

    workspace = _open_workspace(root)
    catalog = CachedCatalogClient(HttpCatalogClient(), workspace.cache("catalog"))
    ctx = RunContext(workspace=workspace, catalog=catalog)

    names = _listing_names(workspace) if all else [listing] if listing else []
    if not names:
        typer.echo("no listings found" if all else f"no such listing: {listing}", err=True)
        raise typer.Exit(code=1)

    exit_code = 0
    for name in names:
        try:
            _load_listing(workspace, name)
        except ConfigLoadError as exc:
            typer.echo(str(exc), err=True)
            exit_code = 1
            continue

        lock = _read_or_empty_lock(_lock_path(workspace, name))
        stage_plan = build_plan(ctx, name, lock, STAGES)
        typer.echo(format_plan(stage_plan))
        typer.echo("")

    raise typer.Exit(code=exit_code)


@app.command()
def apply(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike"),
    all: bool = typer.Option(False, "--all", help="Apply every listing in the workspace"),
    root: str | None = typer.Option(None, "--root", help="Workspace root override"),
) -> None:
    """Execute every stage the plan identified. Only local stages (render) run
    until later phases add Printify/Etsy."""
    if not listing and not all:
        typer.echo("pass a listing name or --all", err=True)
        raise typer.Exit(code=1)

    workspace = _open_workspace(root)
    catalog = CachedCatalogClient(HttpCatalogClient(), workspace.cache("catalog"))
    ctx = RunContext(
        workspace=workspace, catalog=catalog, on_event=lambda msg: typer.echo(f"  {msg}")
    )

    names = _listing_names(workspace) if all else [listing] if listing else []
    if not names:
        typer.echo("no listings found" if all else f"no such listing: {listing}", err=True)
        raise typer.Exit(code=1)

    exit_code = 0
    for name in names:
        try:
            _load_listing(workspace, name)
        except ConfigLoadError as exc:
            typer.echo(str(exc), err=True)
            exit_code = 1
            continue

        lock_path = _lock_path(workspace, name)
        lock = _read_or_empty_lock(lock_path)
        stage_plan = build_plan(ctx, name, lock, STAGES)
        typer.echo(f"applying {name}")
        new_lock = execute(ctx, stage_plan, lock, STAGES)
        new_lock.write(lock_path)

    raise typer.Exit(code=exit_code)


@app.command()
def new(
    design: str = typer.Argument(..., help="Design name, matching designs/<name>.png"),
    category: str = typer.Option("tshirt", "--category", help="Blueprint category filter"),
    root: str | None = typer.Option(None, "--root", help="Workspace root override"),
) -> None:
    """Interactive garment/provider picker; writes profile (if absent) + listing."""
    from etsy_listings.newcmd.interactive import run_new

    workspace = _open_workspace(root)
    catalog = CachedCatalogClient(HttpCatalogClient(), workspace.cache("catalog"))
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
