"""Typer CLI. One module per command; this module wires them into one app.

``plan``, ``apply``, ``new``, ``ui``, ``setup``, ``auth`` and ``unlock`` are
built, per A10's strict phase order. ``catalog refresh`` and ``status``
remain for Phase 6.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer

from etsy_listings import prompts, terminal
from etsy_listings.authcmd import ALL_PARTS as ALL_AUTH_PARTS
from etsy_listings.authcmd import Part as AuthPart
from etsy_listings.cli.render import format_blocked, format_plan
from etsy_listings.clients.etsy import (
    EtsyListingClient,
    HttpEtsyListingClient,
    OAuthClient,
    TokenStore,
)
from etsy_listings.clients.etsy import Transport as EtsyTransport
from etsy_listings.clients.printify import (
    CachedCatalogClient,
    CatalogClient,
    HttpCatalogClient,
    HttpPrintifyClient,
    PrintifyAuthError,
    PrintifyClient,
    Transport,
)
from etsy_listings.config.defaults import MissingDefaultError
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    PRINTIFY_TOKEN_VAR,
    MissingCredentialError,
    Secrets,
)
from etsy_listings.engine.change import Plan
from etsy_listings.engine.context import Event, EventSink, RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun
from etsy_listings.engine.run import RunReport, apply_listings, plan_listings
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.errors import UserFacingError
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

    Renders mockups locally, configures the product in Printify, publishes it
    and patches the resulting Etsy listing's copy and media. Idempotent:
    re-running against unchanged inputs makes no remote changes.
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


def _transport(workspace: Workspace) -> Transport:
    """One connection to Printify, with its token resolved lazily.

    ``plan`` and ``apply`` build a ``RunContext`` eagerly, but no Phase 0/1
    stage calls Printify at all, and a cached catalog read never needs a token
    either. Resolving one at construction time would make every ``plan`` fail
    in a workspace that has no ``.env`` -- including the fixture workspace the
    getting-started guide points at.

    Shared by both clients because it is one host and one token: they differ in
    what they are allowed to *ask*, which is a matter of which protocol the
    caller holds, not of which socket the bytes leave through.
    """

    def token() -> str:
        return Secrets.load(workspace.env_file()).require_printify_api_token()

    return Transport(token)


def _clients(workspace: Workspace) -> tuple[CatalogClient, PrintifyClient]:
    transport = _transport(workspace)
    return (
        CachedCatalogClient(HttpCatalogClient(transport), workspace.catalog_cache_dir()),
        HttpPrintifyClient(transport),
    )


def _etsy_client(workspace: Workspace) -> EtsyListingClient | None:
    """The signed-in Etsy connection Phase 3's stages write through, or
    ``None`` before `auth etsy` has run.

    Checked without raising, unlike :meth:`Secrets.require_etsy_app_key`:
    `plan` in a workspace that has never touched Etsy must not be made to
    configure it just to render mockups -- the same reason
    :func:`_transport` resolves Printify's token lazily, one level further
    in here because :class:`~etsy_listings.clients.etsy.transport.Transport`
    takes its app key pair eagerly rather than through a callable, unlike
    Printify's bearer.
    """
    secrets = Secrets.load(workspace.env_file())
    if not (secrets.etsy_keystring and secrets.etsy_shared_secret):
        return None
    app_key = secrets.require_etsy_app_key()
    store = TokenStore(
        workspace.root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE,
        refresh=lambda token: OAuthClient(app_key.keystring).refresh(token),
    )
    transport = EtsyTransport(app_key, bearer=store.access_token)
    return HttpEtsyListingClient(transport)


def _run_context(workspace: Workspace, on_event: EventSink | None = None) -> RunContext:
    catalog, printify = _clients(workspace)
    etsy = _etsy_client(workspace)
    if on_event is None:
        return RunContext(workspace=workspace, catalog=catalog, printify=printify, etsy=etsy)
    return RunContext(
        workspace=workspace, catalog=catalog, printify=printify, etsy=etsy, on_event=on_event
    )


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


def _echo_blocked(plan: Plan) -> None:
    """Say what this apply will *not* do, before it does the rest.

    A blocked stage is not a failure -- the render stage still runs, and a
    workspace that has not opted into Printify yet is not broken -- but it is
    the half of the run the user cannot see happening, so it must be said out
    loud rather than inferred from a product that never appears.
    """
    for stage_plan in plan.stage_plans:
        if stage_plan.blocked:
            for line in format_blocked(stage_plan):
                typer.echo(line, err=True)


def _echo_failure(listing: str, error: UserFacingError) -> None:
    """One listing's refusal, as a message rather than a stack.

    Every refusal the user can act on -- a config error, a design too small, a
    colour that does not exist, copy still carrying a sentinel -- reaches here
    instead of ending the run: PRD 16 is why one bad listing cannot halt fifty
    good ones. The engine decides that; this only says it out loud.
    """
    typer.echo(f"{listing}: {error}", err=True)
    typer.echo("", err=True)


def _target_listings(workspace: Workspace, listing: str | None, every: bool) -> list[str]:
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
    """Run an interactive command, and leave quietly if the user does.

    Ctrl-C out of a picker is an ordinary way to abandon a wizard, not a
    crash, so it earns a line and a non-zero exit rather than a traceback.
    Caught here because it is the same answer for both wizards, and because
    every question inside them used to check for it individually -- fourteen
    checks, and two `_cancelled()` helpers that disagreed about whether to
    print anything.
    """
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
        help=(
            "Where to create the workspace. Defaults to the current directory. "
            "Unlike every other command, this one does not need a shop.yaml to "
            "exist there already -- it is the command that writes one."
        ),
        envvar=layout.ROOT_ENV_VAR,
        show_envvar=True,
        metavar="PATH",
    ),
) -> None:
    """Initialise a workspace: directories, shop.yaml, and the Printify token.

    Safe to re-run: it fills in what is missing and leaves existing answers
    alone. Verifies the token against Printify before storing it, and reads
    the shop id back from the same call rather than asking you to find one.

    Stops before Etsy sign-in, which arrives with `auth` in Phase 3.
    """
    from etsy_listings.setupcmd import run_setup

    target = to_native_path(root) if root else Path.cwd()
    with _wizard():
        run_setup(target)


auth_app = typer.Typer(
    epilog=EPILOG,
    invoke_without_command=True,
    help="Capture every credential: Printify, Etsy, and the Anthropic key.",
)
app.add_typer(auth_app, name="auth")


def _check_option() -> Any:  # noqa: ANN401 - typer.Option is typed Any at this boundary
    return typer.Option(
        False,
        "--check",
        help="Report what is stored and how long the Etsy consent has left. Writes nothing.",
    )


def _auth_root_option() -> Any:  # noqa: ANN401 - typer.Option is typed Any at this boundary
    """``--root`` as `auth` needs it: no shop.yaml required.

    `auth` and `setup` are the two commands that run *before* a workspace
    exists, so neither can discover one by walking up for its marker file --
    they take the directory they are given (PRD 49).
    """
    return typer.Option(
        None,
        "--root",
        help=(
            "Which workspace to store credentials in. Defaults to the current "
            "directory; unlike most commands this one does not need a shop.yaml "
            "to exist there yet."
        ),
        envvar=layout.ROOT_ENV_VAR,
        show_envvar=True,
        metavar="PATH",
    )


def _run_auth(root: str | None, check: bool, parts: Sequence[AuthPart]) -> None:
    from etsy_listings.authcmd import run_auth

    target = to_native_path(root) if root else Path.cwd()
    with _wizard():
        run_auth(target, check=check, parts=parts)


@auth_app.callback(invoke_without_command=True)
def auth(
    ctx: typer.Context,
    root: str | None = _auth_root_option(),
    check: bool = _check_option(),
) -> None:
    """Capture every credential: Printify, Etsy, and the Anthropic key.

    Verifies each one against its own API before storing it, and signs in to
    Etsy through the browser. Keys go to the workspace's .env, OAuth tokens to
    .auth/, and both are gitignored before the first one is written.

    Run one at a time with `auth printify`, `auth etsy` or `auth anthropic`.
    Safe to re-run: it fills in what is missing, leaves what is present alone,
    and is how you renew the Etsy consent before its 90 days are up.
    """
    if ctx.invoked_subcommand is not None:
        return
    _run_auth(root, check, ALL_AUTH_PARTS)


@auth_app.command("printify", epilog=EPILOG)
def auth_printify(
    root: str | None = _auth_root_option(),
    check: bool = _check_option(),
) -> None:
    """Capture just the Printify API token, verified against the live API."""
    _run_auth(root, check, ["printify"])


@auth_app.command("etsy", epilog=EPILOG)
def auth_etsy(
    root: str | None = _auth_root_option(),
    check: bool = _check_option(),
) -> None:
    """Capture just the Etsy app key pair and sign in through the browser."""
    _run_auth(root, check, ["etsy"])


@auth_app.command("anthropic", epilog=EPILOG)
def auth_anthropic(
    root: str | None = _auth_root_option(),
    check: bool = _check_option(),
) -> None:
    """Capture just the Anthropic API key (used by `generate`, from Phase 4)."""
    _run_auth(root, check, ["anthropic"])


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

    def show(name: str, planned: PlannedRun) -> None:
        typer.echo(format_plan(planned.plan))
        typer.echo("")

    _exit_for(
        plan_listings(
            _run_context(workspace),
            _target_listings(workspace, listing, all),
            STAGES,
            on_planned=show,
            on_failure=_echo_failure,
        )
    )


@app.command(epilog=EPILOG)
def apply(
    listing: str | None = typer.Argument(None, help="Listing name, e.g. take-a-hike"),
    all: bool = typer.Option(False, "--all", help="Apply every listing in the workspace"),
    root: str | None = _root_option(),
) -> None:
    """Execute every stage the plan identified: render, create or update the
    Printify product, publish it, and patch the resulting Etsy listing's
    copy and media. A stage a workspace has not configured (no Printify or
    Etsy shop id) reports itself blocked rather than running."""
    workspace = _open_workspace(root)

    def announce(name: str, planned: PlannedRun) -> None:
        """The header and the refusals, before the work they frame.

        ``on_planned`` fires between planning and executing, which is the only
        point at which both are true: the plan is known, and none of its
        progress events have been printed yet.
        """
        typer.echo(f"applying {name}")
        _echo_blocked(planned.plan)

    _exit_for(
        apply_listings(
            _run_context(workspace, on_event=_echo_event),
            _target_listings(workspace, listing, all),
            STAGES,
            on_planned=announce,
            on_failure=_echo_failure,
        )
    )


@app.command(epilog=EPILOG)
def unlock(
    listing: str = typer.Argument(help="Listing name, e.g. take-a-hike"),
    root: str | None = _root_option(),
) -> None:
    """Clear a Printify product stuck publishing (`is_locked: true`).

    `publish` polls for up to ~10 minutes before giving up; this calls
    Printify's own remedy (`publishing_failed.json`) for the product that
    poll named. Its one job has never been exercised against a genuinely
    stuck publish -- none has stuck in probing -- so it ships built and
    unverified rather than withheld. Re-run `apply` afterwards; this command
    only asks Printify to clear the lock, it does not touch the lockfile.
    """
    workspace = _open_workspace(root)
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
    printify = _clients(workspace)[1]
    printify.publishing_failed(
        shop_id, str(product_id), reason="cleared via `etsy-listings unlock`"
    )
    typer.echo(f"{listing}: asked Printify to clear the publish lock on product {product_id}")
    typer.echo("Run `etsy-listings apply` again to continue.")


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
    """Interactive design/garment/provider picker; writes garment profile (if absent) + listing.

    Reads Printify's catalog, so it needs PRINTIFY_API_TOKEN with the
    `catalog.read` scope (see the environment variables below).
    """
    from etsy_listings.newcmd.interactive import run_new

    workspace = _open_workspace(root)
    try:
        with _wizard():
            run_new(workspace, _clients(workspace)[0], design, category)
    except (MissingCredentialError, PrintifyAuthError) as exc:
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
