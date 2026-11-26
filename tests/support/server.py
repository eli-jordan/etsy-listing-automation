"""Starting and stopping a uvicorn server a browser test runs in a thread."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import uvicorn

GRACEFUL_SECONDS = 10
STARTUP_TIMEOUT_SECONDS = 30


@contextmanager
def serve(app: Any, *, name: str) -> Iterator[str]:
    """Serve ``app`` on a free loopback port; yields its base URL.

    The socket is bound to port 0 here and handed to uvicorn still open, so
    no other process can take the port between choosing it and listening on
    it. Choosing a port by binding and closing a probe socket, then letting
    uvicorn bind it again, left that window open: under xdist another
    worker's server took the port first (``[Errno 98] address already in
    use`` on Linux CI).
    """
    listening = socket.socket()
    listening.bind(("127.0.0.1", 0))
    port: int = listening.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listening]}, daemon=True)
    thread.start()
    try:
        _wait_started(server, name)
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_server(server, thread)
        listening.close()


def _wait_started(server: uvicorn.Server, name: str) -> None:
    deadline = threading.Event()
    for _ in range(STARTUP_TIMEOUT_SECONDS * 20):
        if server.started:
            return
        deadline.wait(0.05)
    pytest.fail(f"{name} did not start in time")  # pragma: no cover - a pathologically slow machine


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
        state.ai.stop()
        state.deployments.stop()
