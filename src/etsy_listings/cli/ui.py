from __future__ import annotations

import typer

from etsy_listings.cli.options import open_workspace, root_option


def ui(
    root: str | None = root_option(),
    host: str = typer.Option(
        "0.0.0.0",
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
    from etsy_listings.server.hosting import (  # noqa: PLC0415 -- only `ui` pays the server's import cost (ADR-0052)
        serve,
    )

    serve(open_workspace(root), host=host, port=port)
