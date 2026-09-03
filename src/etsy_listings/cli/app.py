"""Typer CLI. One module per command; this module wires them into one app.

Only ``plan`` exists in Phase 0/1 -- the rest of the PRD's CLI table (``apply``,
``new``, ``auth``, ...) is built in later phases, per A10's strict phase order.
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
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan, format_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.workspace.layout import LISTINGS_DIR
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


def _open_workspace(root: Path | None) -> Workspace:
    try:
        return Workspace.discover(root_override=root)
    except WorkspaceNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _listing_names(workspace: Workspace) -> list[str]:
    listings_dir = workspace.root / LISTINGS_DIR
    if not listings_dir.is_dir():
        return []
    return sorted(p.name for p in listings_dir.iterdir() if (p / "listing.yaml").is_file())


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
    root: Path | None = typer.Option(None, "--root", help="Workspace root override"),
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

        lock_path = workspace.root / LISTINGS_DIR / name / "state.lock.json"
        lock = Lockfile.read(lock_path) or Lockfile.empty(
            tool_version=__about__.VERSION, applied_at=datetime.now(UTC).isoformat()
        )
        stage_plan = build_plan(ctx, name, lock, STAGES)
        typer.echo(format_plan(stage_plan))
        typer.echo("")

    raise typer.Exit(code=exit_code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
