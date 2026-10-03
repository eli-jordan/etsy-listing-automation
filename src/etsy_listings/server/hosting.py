"""Serve the workspace's HTTP app in the foreground.

This is the server's startup interface: what ``etsy-listings ui``
(``cli/ui.py``) calls, and the only server module the CLI may import
(ADR-0052; the Import Linter contracts in ``pyproject.toml``). The
module-structure specification removed the native pywebview window: the
command serves HTTP and the user opens the printed URL in any browser. It is
the former ``--browser`` path unchanged -- uvicorn on the main thread, where
it owns the Ctrl-C handling.

Shutdown goes through the ASGI lifespan ``create_app`` wires up: uvicorn
waits for it without a timeout, so a queued run is cancelled, a plan run
stops at its next boundary and an apply run finishes the stage it is in
(ADR-0037).
"""

from __future__ import annotations

import uvicorn

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app


def serve(
    workspace: Workspace,
    *,
    host: str = "0.0.0.0",  # noqa: S104 -- LAN reachability is the documented default
    port: int = 8000,
) -> None:
    """Block serving ``workspace`` over HTTP until the process is interrupted."""
    uvicorn.run(create_app(workspace), host=host, port=port)
