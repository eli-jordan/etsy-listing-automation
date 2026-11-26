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


def root_option() -> Any:  # typer.Option is typed Any at this boundary
    return typer.Option(
        None,
        "--root",
        help=ROOT_HELP,
        envvar=layout.ROOT_ENV_VAR,
        show_envvar=True,
        metavar="PATH",
    )


def open_workspace(root: str | None) -> Workspace:
    try:
        return Workspace.discover(root_override=to_native_path(root) if root else None)
    except WorkspaceNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
