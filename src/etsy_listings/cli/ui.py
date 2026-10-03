"""The ``ui`` command: the CLI's launcher for the HTTP server.

This is the only CLI module allowed to import the server, and only its
startup interface, :mod:`etsy_listings.server.hosting` (ADR-0052; the
module-structure spec's Import Linter table). The import sits inside the
command body, so ``cli/app.py`` registering this command -- which every CLI
invocation does -- loads neither FastAPI nor uvicorn.
"""

from __future__ import annotations

import typer

from etsy_listings.cli.options import open_workspace, root_option


def ui(
    root: str | None = root_option(),
    host: str = typer.Option(
        "0.0.0.0",  # noqa: S104 -- see the option help
        "--host",
        help="Interface to bind the server to. The default reaches the workspace "
        "from another machine on the LAN; pass 127.0.0.1 for loopback only.",
    ),
    port: int = typer.Option(8000, "--port", help="Port to serve on"),
) -> None:
    """Serve the UI over HTTP in the foreground; open the printed URL in a browser.

    The UI includes the dashboard, calibrator, listing editor and run runner.
    Ctrl-C stops the server once any in-flight apply finishes its current stage.
    """
    from etsy_listings.server.hosting import serve

    serve(open_workspace(root), host=host, port=port)
