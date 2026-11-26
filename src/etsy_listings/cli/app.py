from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from etsy_listings.cli import prompts, terminal
from etsy_listings.cli.auth import ALL_PARTS as ALL_AUTH_PARTS
from etsy_listings.cli.auth import Part as AuthPart
from etsy_listings.cli.auth import run_auth
from etsy_listings.cli.backup import app as backup_app
from etsy_listings.cli.marigold import app as marigold_app
from etsy_listings.cli.new import run_new
from etsy_listings.cli.options import RootOption, open_workspace
from etsy_listings.cli.render import format_blocked, format_plan
from etsy_listings.cli.setup import run_setup
from etsy_listings.cli.ui import ui
from etsy_listings.core import connections
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR
from etsy_listings.core.clients.printify import (
    PrintifyAuthError,
    PrintifyClient,
)
from etsy_listings.core.config.defaults import MissingDefaultError
from etsy_listings.core.config.secrets import (
    BACKUP_PASSWORD_VAR,
    PRINTIFY_TOKEN_VAR,
    MissingCredentialError,
)
from etsy_listings.core.engine.change import Plan
from etsy_listings.core.engine.context import Event
from etsy_listings.core.engine.events import (
    EngineListingFailed,
    EngineListingPlanned,
    EngineRunEvent,
    RunHooks,
)
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.run import RunReport, apply_listings, plan_listings
from etsy_listings.core.engine.stages import STAGES, publishing_pipeline
from etsy_listings.core.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.core.workspace.workspace import Workspace

_ENVIRONMENT = {
    layout.ROOT_ENV_VAR: "the workspace, as --root sets it (--root wins)",
    PRINTIFY_TOKEN_VAR: "the Printify API token",
    BACKUP_PASSWORD_VAR: "the backup repository's password",
    RESTIC_BINARY_ENV_VAR: "a restic to run instead of the pinned download",
    "NO_COLOR": "turn off the colour swatches apply prints",
    "FORCE_COLOR": "print them when stdout is not a terminal, as in cygwin",
}
_NAME_WIDTH = max(map(len, _ENVIRONMENT))
_VARIABLES = "\n".join(
    f"  [cyan]{name.ljust(_NAME_WIDTH)}[/cyan]  {text}" for name, text in _ENVIRONMENT.items()
)

EPILOG = f"""
[bold]Environment variables[/bold]

{_VARIABLES}

Paths accept cygwin, /cygdrive and Windows forms. Secrets live in the
workspace .env, which the process environment overrides. See docs/guides/setup.md.
"""

app = typer.Typer(no_args_is_help=True, epilog=EPILOG)
app.add_typer(marigold_app, name="marigold")
app.add_typer(backup_app, name="backup")


@app.callback(epilog=EPILOG)
def _root_callback() -> None:
    """Turn print-on-demand designs into Etsy listings.

    Renders mockups locally, sets up each product in Printify and updates its
    Etsy listing. Re-running on unchanged files makes no remote changes.
    """


SWATCH_GLYPH = "██"
SWATCH_FALLBACK = "##"


def _swatch_glyph() -> str | None:
    """The block to print per colour, or ``None`` when swatches are off.

    ``FORCE_COLOR`` overrides a non-terminal stdout because a cygwin pty is a
    named pipe: native-Windows Python reports ``isatty()`` false inside one
    even though the terminal on the other end renders colour.
    """
    if os.environ.get("NO_COLOR"):
        return None
    if not (os.environ.get("FORCE_COLOR") or sys.stdout.isatty()):
        return None
    return terminal.choose(SWATCH_GLYPH, SWATCH_FALLBACK)


def _echo_event(event: Event) -> None:
    """Progress line, prefixed with one colour block per garment the scene shows."""
    glyph = _swatch_glyph() if event.swatches else None
    if glyph is None:
        typer.echo(f"  {event.message}")
        return
    swatch = "".join(typer.style(glyph, fg=colour) for colour in event.swatches)
    typer.echo(f"  {swatch} {event.message}", color=True)


def _echo_blocked(plan: Plan) -> None:
    """Say what this apply will *not* do, before it does the rest."""
    for stage_plan in plan.stage_plans:
        if stage_plan.blocked:
            for line in format_blocked(stage_plan):
                typer.echo(line, err=True)


def _echo_failure(listing: str, error: UserFacingError) -> None:
    typer.echo(f"{listing}: {error}", err=True)
    typer.echo("", err=True)


def _target_listings(workspace: Workspace, listing: str | None, *, every: bool) -> list[str]:
    if not listing and not every:
        typer.echo("pass a listing name or --all", err=True)
        raise typer.Exit(code=1)

    names = workspace.listing_names() if every else [listing] if listing else []
    if not names:
        typer.echo("no listings found" if every else f"no such listing: {listing}", err=True)
        raise typer.Exit(code=1)
    return names


def _exit_for(report: RunReport) -> None:
    raise typer.Exit(code=1 if report.failed else 0)


@contextmanager
def _wizard() -> Iterator[None]:
    """Run an interactive command, and leave quietly if the user does."""
    try:
        yield
    except prompts.Cancelled as exc:
        typer.echo("cancelled", err=True)
        raise typer.Exit(code=1) from exc


@app.command(epilog=EPILOG)
def setup(
    root: str | None = typer.Option(
        None,
        "--root",
        help="Where to create the workspace. Defaults to the current directory.",
        envvar=layout.ROOT_ENV_VAR,
        show_envvar=True,
        metavar="PATH",
    ),
    *,
    replace_prompts: Annotated[
        bool,
        typer.Option(
            "--replace-prompts",
            help=(
                "Replace each prompt in prompts/ that differs from its packaged "
                "default, keeping yours as <name>.md.bak."
            ),
        ),
    ] = False,
) -> None:
    """Create a workspace, or fill in what one is missing.

    Writes the folders and shop.yaml, and stores the Printify token once
    Printify accepts it, taking the shop id from that answer. Safe to re-run: existing answers and
    edited prompts are kept, and an edited prompt is named in a warning. With
    Etsy credentials stored (`auth etsy`), it also looks up the Etsy shop and
    its return policy.
    """

    target = to_native_path(root) if root else Path.cwd()
    with _wizard():
        run_setup(target, replace_prompts=replace_prompts)


auth_app = typer.Typer(
    epilog=EPILOG,
    invoke_without_command=True,
)
app.add_typer(auth_app, name="auth")


CheckOption = Annotated[
    bool,
    typer.Option(
        "--check",
        help="Report what is stored and how long the Etsy sign-in has left, writing nothing.",
    ),
]


AuthRootOption = Annotated[
    str | None,
    typer.Option(
        "--root",
        help="Which workspace to store credentials in. Defaults to the current directory.",
        envvar=layout.ROOT_ENV_VAR,
        show_envvar=True,
        metavar="PATH",
    ),
]


def _run_auth(root: str | None, parts: Sequence[AuthPart], *, check: bool) -> None:

    target = to_native_path(root) if root else Path.cwd()
    with _wizard():
        run_auth(target, check=check, parts=parts)


@auth_app.callback(invoke_without_command=True)
def auth(
    ctx: typer.Context,
    root: AuthRootOption = None,
    *,
    check: CheckOption = False,
) -> None:
    """Store and check the Printify and Etsy credentials.

    Checks each one with its own API before storing it, and signs in to Etsy
    in the browser. Keys go to the workspace .env and the Etsy sign-in to
    .auth/, both gitignored. Safe to re-run: it fills in what is missing, and
    renews the Etsy sign-in before it expires.
    """
    if ctx.invoked_subcommand is not None:
        return
    _run_auth(root, ALL_AUTH_PARTS, check=check)


@auth_app.command("printify", epilog=EPILOG)
def auth_printify(
    root: AuthRootOption = None,
    *,
    check: CheckOption = False,
) -> None:
    """Store the Printify API token, checked with Printify."""
    _run_auth(root, ["printify"], check=check)


@auth_app.command("etsy", epilog=EPILOG)
def auth_etsy(
    root: AuthRootOption = None,
    *,
    check: CheckOption = False,
) -> None:
    """Store the Etsy app key pair, then sign in to Etsy in the browser."""
    _run_auth(root, ["etsy"], check=check)


PublishOption = Annotated[
    bool,
    typer.Option(
        "--publish",
        help=(
            "Publish new and draft listings on Etsy, which charges its listing fee, "
            "rather than leave them drafts. Paused and retired listings are never touched."
        ),
    ),
]


@app.command(epilog=EPILOG)
def plan(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike."),
    *,
    all_: Annotated[
        bool, typer.Option("--all", help="Plan every listing in the workspace.")
    ] = False,
    publish: PublishOption = False,
    root: RootOption = None,
) -> None:
    """Show what apply would change, without changing anything.

    Compares each listing with what was last applied and with Printify and
    Etsy, and lists every step apply would take with the files it reads and
    writes.
    """
    workspace = open_workspace(root)

    def show(event: EngineRunEvent) -> None:
        if isinstance(event, EngineListingPlanned):
            typer.echo(format_plan(event.plan))
            typer.echo("")
        elif isinstance(event, EngineListingFailed):
            _echo_failure(event.listing, event.error)

    _exit_for(
        plan_listings(
            connections.run_context(workspace),
            _target_listings(workspace, listing, every=all_),
            publishing_pipeline(STAGES, publish=publish),
            hooks=RunHooks(on_event=show),
        )
    )


@app.command(epilog=EPILOG)
def apply(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike."),
    *,
    all_: Annotated[
        bool, typer.Option("--all", help="Apply every listing in the workspace.")
    ] = False,
    publish: PublishOption = False,
    root: RootOption = None,
) -> None:
    """Make the changes plan shows: render, update Printify, then Etsy.

    A step the workspace has not configured (no Printify or Etsy shop id) is
    reported as blocked and skipped. New listings stay Etsy drafts unless you
    pass --publish; `plan --publish` shows which it would publish."""
    workspace = open_workspace(root)

    def announce(event: EngineRunEvent) -> None:
        if isinstance(event, EngineListingPlanned):
            typer.echo(f"applying {event.listing}")
            _echo_blocked(event.plan)
        elif isinstance(event, EngineListingFailed):
            _echo_failure(event.listing, event.error)

    _exit_for(
        apply_listings(
            connections.run_context(workspace, on_event=_echo_event),
            _target_listings(workspace, listing, every=all_),
            publishing_pipeline(STAGES, publish=publish),
            hooks=RunHooks(on_event=announce),
        )
    )


@app.command(epilog=EPILOG)
def unlock(
    listing: str = typer.Argument(help="Listing name, e.g. take-a-hike."),
    root: RootOption = None,
) -> None:
    """Clear a Printify product stuck publishing.

    Asks Printify to release the product's publish lock and changes nothing
    else, so run `apply` again afterwards.
    """
    unlock_listing(open_workspace(root), listing, connections.printify_client)


def unlock_listing(
    workspace: Workspace, listing: str, printify_client: Callable[[Workspace], PrintifyClient]
) -> None:
    lock = Lockfile.read(workspace.lock_file(listing))
    product_id = lock.remote.get(PRODUCT_ID_KEY) if lock is not None else None
    if not product_id:
        typer.echo(f"{listing}: no Printify product on record -- nothing to unlock", err=True)
        raise typer.Exit(code=1)

    try:
        shop_id = workspace.defaults.printify.require_shop_id()
    except MissingDefaultError as exc:
        typer.echo(f"{listing}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    printify = printify_client(workspace)
    printify.publishing_failed(
        shop_id, str(product_id), reason="cleared via `etsy-listings unlock`"
    )
    typer.echo(f"{listing}: asked Printify to clear the publish lock on product {product_id}")
    typer.echo("Run `etsy-listings apply` again to continue.")


@app.command(epilog=EPILOG)
def new(
    design: str | None = typer.Argument(
        None, help="Design name, as in designs/<name>.png. Omit it to pick one."
    ),
    category: str = typer.Option(
        "tshirt",
        "--category",
        help="Offer only Printify products whose title, brand or model contains this.",
    ),
    root: RootOption = None,
) -> None:
    """Create a listing by picking a design, a garment and a print provider.

    Also writes the garment's profile when it has none. Reads Printify's
    catalog, so it needs a Printify token with the catalog.read scope.
    """

    workspace = open_workspace(root)
    try:
        with _wizard():
            run_new(workspace, connections.catalog_client(workspace), design, category)
    except (MissingCredentialError, PrintifyAuthError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


app.command(epilog=EPILOG)(ui)


def main() -> None:
    terminal.adopt_declared_encoding()
    try:
        app()
    except OSError as exc:
        if not terminal.stdout_reader_gone(exc):
            raise
        terminal.discard_stdout()
        sys.exit(1)


if __name__ == "__main__":
    main()
