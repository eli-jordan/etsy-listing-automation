from __future__ import annotations

import typer

from etsy_listings.cli.options import RootOption, open_workspace


def ui(
    root: RootOption = None,
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        help="Network interface to listen on. The default lets other machines on your "
        "network reach it; pass 127.0.0.1 for this machine only.",
    ),
    port: int = typer.Option(8000, "--port", help="Port to listen on."),
) -> None:
    """Serve the web UI in the foreground; open the URL it prints in a browser.

    It holds the dashboard, listings and their editor, batches, listing
    templates, the calibrator, runs and settings. Ctrl-C stops it once any
    running apply finishes its current step.
    """
    from etsy_listings.server.hosting import (  # noqa: PLC0415 -- only `ui` pays the server's import cost (ADR-0052)
        serve,
    )

    serve(open_workspace(root), host=host, port=port)
