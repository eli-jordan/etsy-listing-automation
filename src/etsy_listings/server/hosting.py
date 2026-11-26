"""Serve the workspace's HTTP app in the foreground for ``etsy-listings ui``,
with uvicorn on the main thread, where it owns Ctrl-C.

Shutdown runs the ASGI lifespan with no timeout, so a queued run is cancelled,
a plan run stops at its next boundary and an apply run finishes its stage."""

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
