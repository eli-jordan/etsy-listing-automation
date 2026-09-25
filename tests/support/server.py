"""Stopping a uvicorn server a browser test ran in a thread."""

from __future__ import annotations

import threading

import uvicorn

GRACEFUL_SECONDS = 10


def stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    """Ask for a graceful shutdown, and force one if it does not come.

    A graceful shutdown waits for every open request to finish before it runs
    the app's lifespan shutdown -- which is what stops the runs executor's
    worker thread and cancels AI runs. A request still open when a test ends
    (a stream the page never closed cleanly) would hold that up, so
    ``force_exit`` skips the wait.

    But ``force_exit`` also skips the lifespan shutdown (uvicorn's
    ``Server.shutdown``: ``if not self.force_exit``), and the executor's
    thread is deliberately not a daemon: left running, it kept pytest alive
    after its summary. So a forced stop stops the app's workers itself.
    """
    server.should_exit = True
    thread.join(timeout=GRACEFUL_SECONDS)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=GRACEFUL_SECONDS)
    if server.force_exit:
        state = server.config.app.state
        state.ai_runner.shutdown()
        state.run_executor.stop()
