"""Stopping a uvicorn server a browser test ran in a thread."""

from __future__ import annotations

import threading

import uvicorn

GRACEFUL_SECONDS = 10


def stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    """Ask for a graceful shutdown, and force one if it does not come.

    A graceful shutdown waits for every open request to finish before it runs
    the app's lifespan shutdown -- which is what stops the runs executor's
    worker thread. That thread is deliberately not a daemon, so a request
    still open when a test ends (a stream the page never closed cleanly)
    used to leave pytest alive after its summary, holding the thread
    forever. ``force_exit`` skips the wait and still runs the lifespan
    shutdown.
    """
    server.should_exit = True
    thread.join(timeout=GRACEFUL_SECONDS)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=GRACEFUL_SECONDS)
