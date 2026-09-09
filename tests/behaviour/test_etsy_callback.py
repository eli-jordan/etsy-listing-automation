"""The loopback server that catches Etsy's redirect, driven over a real socket.

Behaviour rather than unit, because the thing worth testing is not a function
-- it is that a browser hitting this address gets a page and the flow gets a
code. So the requests here are real HTTP over loopback, on a port the test
picks; only the port differs from what `auth` runs.
"""

from __future__ import annotations

import socket
import threading
from typing import Any

import httpx
import pytest

from etsy_listings.clients.etsy.callback import CallbackError, wait_for_redirect
from etsy_listings.clients.etsy.oauth import OAuthError


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Waiting:
    """`wait_for_redirect` running in a thread, with whatever it produced."""

    def __init__(self, uri: str, timeout: float = 10.0) -> None:
        self.uri = uri
        self.result: Any = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(timeout,), daemon=True)
        self._thread.start()

    def _run(self, timeout: float) -> None:
        try:
            self.result = wait_for_redirect(redirect_uri=self.uri, timeout=timeout)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the test's thread
            self.error = exc

    def get(self, query: str) -> httpx.Response:
        """Request the callback, retrying while the server is still binding."""
        for _ in range(50):
            try:
                return httpx.get(f"{self.uri}?{query}", timeout=5.0)
            except httpx.ConnectError:
                self._thread.join(0.05)
        raise AssertionError(f"nothing ever listened on {self.uri}")

    def finish(self) -> None:
        self._thread.join(timeout=10.0)
        assert not self._thread.is_alive(), "the callback server did not stop"


@pytest.fixture
def uri() -> str:
    return f"http://localhost:{_free_port()}/oauth/callback"


def test_a_redirect_hands_back_the_code_and_state(uri: str) -> None:
    waiting = Waiting(uri)

    response = waiting.get("code=abc123&state=xyz")
    waiting.finish()

    assert response.status_code == 200
    assert waiting.result.code == "abc123"
    assert waiting.result.state == "xyz"


def test_the_browser_is_told_it_can_close_the_tab(uri: str) -> None:
    """The last thing the user sees of this flow, and the only place the
    handover back to the terminal is explained."""
    waiting = Waiting(uri)

    response = waiting.get("code=abc&state=xyz")
    waiting.finish()

    assert "close this tab" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_a_favicon_request_does_not_consume_the_wait(uri: str) -> None:
    """A browser asks for `/favicon.ico` unprompted. Serving exactly one
    request meant that ask could be the one served, leaving the flow waiting
    for a redirect that had already happened."""
    waiting = Waiting(uri)

    base = uri.rsplit("/oauth/callback", 1)[0]
    for _ in range(50):
        try:
            noise = httpx.get(f"{base}/favicon.ico", timeout=5.0)
            break
        except httpx.ConnectError:
            pass
    else:  # pragma: no cover - the server always comes up
        raise AssertionError("nothing ever listened")

    assert noise.status_code == 404
    waiting.get("code=after-the-noise&state=xyz")
    waiting.finish()

    assert waiting.result.code == "after-the-noise"


def test_a_refusal_on_the_consent_screen_becomes_an_oauth_error(uri: str) -> None:
    waiting = Waiting(uri)

    response = waiting.get("error=access_denied&error_description=user+refused")
    waiting.finish()

    assert response.status_code == 400
    assert isinstance(waiting.error, OAuthError)
    assert waiting.error.error == "access_denied"
    assert waiting.error.description == "user refused"


def test_nobody_coming_back_is_reported_rather_than_waited_on_forever(uri: str) -> None:
    waiting = Waiting(uri, timeout=0.2)
    waiting.finish()

    assert isinstance(waiting.error, CallbackError)
    assert "no redirect arrived" in str(waiting.error)


def test_a_port_already_in_use_says_so_and_says_why_it_cannot_move() -> None:
    """The port is registered with the Etsy app, so picking another one would
    produce a redirect Etsy refuses to send."""
    port = _free_port()
    with socket.socket() as held:
        # Deliberately *without* SO_REUSEADDR: on Windows that flag lets a
        # second socket bind an address this one is listening on, which is the
        # hijack `_LoopbackServer` turns off. Setting it here would test the
        # flag rather than the server.
        held.bind(("127.0.0.1", port))
        held.listen(1)

        with pytest.raises(CallbackError) as caught:
            wait_for_redirect(redirect_uri=f"http://localhost:{port}/oauth/callback", timeout=0.2)

    assert "already in use" in str(caught.value)
    assert "registered" in str(caught.value)
