"""Serve the workspace's HTTP app in the foreground: the startup interface
``etsy-listings ui`` calls, and the only server module the CLI may import
(ADR-0052). Uvicorn runs on the main thread, where it owns the Ctrl-C handling.

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
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    uvicorn.run(create_app(workspace), host=host, port=port)
