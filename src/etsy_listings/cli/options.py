"""Workspace selection shared by CLI commands: the ``--root`` option and
opening the workspace it names.

Its own module so a command defined outside ``cli/app.py`` -- the ``ui``
launcher in ``cli/ui.py`` -- declares ``--root`` exactly as every other
command does, without importing the module that registers it.
"""

from __future__ import annotations

from typing import Any

import typer

from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.core.workspace.workspace import Workspace, WorkspaceNotFoundError

ROOT_HELP = (
    "Workspace root: the directory holding shop.yaml. "
    "Defaults to walking up from the current directory."
)


def root_option() -> Any:  # noqa: ANN401 - typer.Option is typed Any at this boundary
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


def open_workspace(root: str | None) -> Workspace:
    """The workspace at ``root``, or discovered from the current directory;
    exits with status 1 when there is none."""
    try:
        return Workspace.discover(root_override=to_native_path(root) if root else None)
    except WorkspaceNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
