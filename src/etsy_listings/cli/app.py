"""Typer CLI. One module per command; this module wires them into one app.

``plan``, ``apply``, ``new`` and ``ui`` exist as of Phase 1 -- ``auth``,
``catalog refresh``, ``unlock`` and ``status`` are built in later phases, per
A10's strict phase order.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import typer

from etsy_listings import __about__, terminal
from etsy_listings.catalog.cache import CachedCatalogClient
from etsy_listings.catalog.client import CatalogClient
from etsy_listings.catalog.http import CatalogAuthError, HttpCatalogClient
from etsy_listings.cli.render import format_plan
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    PRINTIFY_TOKEN_VAR,
    MissingCredentialError,
    Secrets,
)
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import Event, EventSink, RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.workspace import layout
from etsy_listings.workspace.userpath import to_native_path
from etsy_listings.workspace.workspace import Workspace, WorkspaceNotFoundError

EPILOG = f"""
[bold]Environment variables[/bold]

  [cyan]{layout.ROOT_ENV_VAR}[/cyan]  workspace root, same as --root (--root wins).
  [cyan]{PRINTIFY_TOKEN_VAR}[/cyan]  Printify token, [cyan]catalog.read[/cyan] scope.
  [cyan]{ANTHROPIC_KEY_VAR}[/cyan]   Anthropic key for copy generation (Phase 4).
  [cyan]NO_COLOR[/cyan]            suppress the colour swatches [cyan]apply[/cyan] prints.
  [cyan]FORCE_COLOR[/cyan]         print them even when stdout looks non-interactive
                      (a cygwin pty is reported as a pipe, not a terminal).

Root paths accept cygwin, /cygdrive and native Windows forms.
Secrets live in the [bold]workspace[/bold] .env (gitignored), never in this repo;
the process environment overrides that file. See docs/setup.md section 4.
"""

ROOT_HELP = (
    "Workspace root: the directory holding shop.yaml. "
    "Defaults to walking up from the current directory."
)

app = typer.Typer(no_args_is_help=True, epilog=EPILOG)


def _root_option() -> Any:  # noqa: ANN401 - typer.Option is typed Any at this boundary
    """One definition of ``--root``, shared by every command that takes a path.

    Declared ``str``, never ``Path``: on Windows ``str(Path("/home/Admin"))``
    is already ``\\home\\Admin``, and a mangled path cannot be told apart from
    a root-relative one. Any new CLI option taking a user-supplied path needs
    the same treatment (see ``workspace/userpath.py``).
    """
    return typer.Option(
        None,
        "--root",
        help=ROOT_HELP,
        envvar=layout.ROOT_ENV_VAR,
        show_envvar=True,
        metavar="PATH",
    )


@app.callback(epilog=EPILOG)
def _root_callback() -> None:
    """Etsy print-on-demand listing automation.

    Renders mockups locally, configures the product in Printify and patches the
    resulting Etsy listing. Idempotent: re-running against unchanged inputs
    makes no remote changes. Only the local `render` stage is implemented so
    far -- `plan` and `apply` are real, and neither touches Printify or Etsy yet.
    """
    # A no-op callback keeps `plan` addressed as a subcommand (`etsy-listings
    # plan ...`) -- Typer otherwise collapses a single-command app so its
    # command name is invisible, which would silently change the CLI surface
    # the moment a second command is added.


def _open_workspace(root: str | None) -> Workspace:
    try:
        return Workspace.discover(root_override=to_native_path(root) if root else None)
    except WorkspaceNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _catalog(workspace: Workspace) -> CatalogClient:
    """The catalog client, with its token resolved lazily.

    ``plan`` and ``apply`` build a ``RunContext`` eagerly, but no Phase 0/1
    stage calls the catalog, and a cached read never needs a token either.
    Resolving one at construction time would make every ``plan`` fail in a
    workspace that has no ``.env`` -- including the fixture workspace the
    getting-started guide points at.
    """

    def token() -> str:
        return Secrets.load(workspace.env_file()).require_printify_api_token()

    return CachedCatalogClient(HttpCatalogClient(token), workspace.catalog_cache_dir())


def _run_context(workspace: Workspace, on_event: EventSink | None = None) -> RunContext:
    catalog = _catalog(workspace)
    if on_event is None:
        return RunContext(workspace=workspace, catalog=catalog)
    return RunContext(workspace=workspace, catalog=catalog, on_event=on_event)


SWATCH_GLYPH = "██"
SWATCH_FALLBACK = "##"


def _swatch_glyph() -> str | None:
    """The block to print per colour, or ``None`` when swatches are off.

    A swatch carries its meaning entirely in its colour, so it is only worth
    printing where it will actually be coloured. Three things can turn it off
    or change it:

    - ``NO_COLOR``, the cross-tool convention, suppresses it outright.
    - A non-terminal stdout suppresses it: a redirected run would otherwise
      collect a column of identical, meaningless blocks. ``FORCE_COLOR``
      overrides that, which is not just symmetry -- a cygwin pty is a named
      pipe, and native-Windows Python reports ``isatty()`` false inside one
      even though the terminal on the other end renders colour perfectly.
    - A stdout that cannot encode the block glyph (a redirected stdout on
      Windows is cp1252, which cannot -- it used to abort ``apply`` with a
      ``UnicodeEncodeError``) falls back to ASCII rather than losing the
      colour, which is the part that carries the information.
    """
    if os.environ.get("NO_COLOR"):
        return None
    if not (os.environ.get("FORCE_COLOR") or sys.stdout.isatty()):
        return None
    try:
        SWATCH_GLYPH.encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        return SWATCH_FALLBACK
    return SWATCH_GLYPH


def _echo_event(event: Event) -> None:
    """Progress line, prefixed with one colour block per garment the scene
    shows. The colour is sampled from the mockup itself, so a run reads as the
    colour set it produced instead of a column of slugs -- and a miscalibrated
    bounding box is visible in the swatch without opening the PNG.

    ``color=True`` where a swatch is printed: the decision that colour is
    wanted has already been made above, so click must not second-guess it by
    stripping the escapes back out.
    """
    glyph = _swatch_glyph() if event.swatches else None
    if glyph is None:
        typer.echo(f"  {event.message}")
        return
    swatch = "".join(typer.style(glyph, fg=colour) for colour in event.swatches)
    typer.echo(f"  {swatch} {event.message}", color=True)


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


@app.command(epilog=EPILOG)
def plan(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike"),
    all: bool = typer.Option(False, "--all", help="Plan every listing in the workspace"),
    root: str | None = _root_option(),
) -> None:
    """Three-way diff against live state; decides which stages need to run.

    Reports every action each stage would take, with the files it reads and
    the files it writes. Reads only -- nothing is created, uploaded or
    published.
    """
    workspace = _open_workspace(root)
    ctx = _run_context(workspace)

    def show_plan(ctx: RunContext, name: str, lock: Lockfile) -> None:
        typer.echo(format_plan(build_plan(ctx, name, lock, STAGES)))
        typer.echo("")

    _run_over_listings(workspace, _target_listings(workspace, listing, all), ctx, show_plan)


@app.command(epilog=EPILOG)
def apply(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike"),
    all: bool = typer.Option(False, "--all", help="Apply every listing in the workspace"),
    root: str | None = _root_option(),
) -> None:
    """Execute every stage the plan identified. Only local stages (render) run
    until later phases add Printify/Etsy."""
    workspace = _open_workspace(root)
    ctx = _run_context(workspace, on_event=_echo_event)

    def run_apply(ctx: RunContext, name: str, lock: Lockfile) -> None:
        typer.echo(f"applying {name}")
        plan = build_plan(ctx, name, lock, STAGES)
        execute(ctx, plan, lock, STAGES).write(workspace.lock_file(name))

    _run_over_listings(workspace, _target_listings(workspace, listing, all), ctx, run_apply)


@app.command(epilog=EPILOG)
def new(
    design: str | None = typer.Argument(
        None, help="Design name, matching designs/<name>.png. Omit to pick from designs/"
    ),
    category: str = typer.Option(
        "tshirt", "--category", help="Blueprint category filter, matched against title/brand/model"
    ),
    root: str | None = _root_option(),
) -> None:
    """Interactive design/garment/provider picker; writes profile (if absent) + listing.

    Reads Printify's catalog, so it needs PRINTIFY_API_TOKEN with the
    `catalog.read` scope (see the environment variables below).
    """
    from etsy_listings.newcmd.interactive import run_new

    workspace = _open_workspace(root)
    try:
        run_new(workspace, _catalog(workspace), design, category)
    except (MissingCredentialError, CatalogAuthError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command(epilog=EPILOG)
def ui(
    root: str | None = _root_option(),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind the server to"),
    port: int = typer.Option(8000, "--port", help="Port to serve on"),
) -> None:
    """Serve the calibrator (Phase 1). The dashboard/setup wizard/run runner
    described in the PRD's ``## UI`` section land in Phase 5."""
    import uvicorn

    from etsy_listings.ui.api.app import create_app

    workspace = _open_workspace(root)
    uvicorn.run(create_app(workspace), host=host, port=port)


def main() -> None:
    # Before Typer, so every command's output is already on a stream that can
    # print what `terminal` is about to ask it for. Here rather than in the
    # Typer callback because it mutates process-global streams, which a test
    # driving `app` through CliRunner should not have done to it.
    terminal.adopt_declared_encoding()
    app()


if __name__ == "__main__":
    main()
