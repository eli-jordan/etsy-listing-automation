"""The loopback server that catches Etsy's redirect."""

from __future__ import annotations

import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

from etsy_listings.core.clients.etsy.oauth import REDIRECT_URI, OAuthError

DEFAULT_TIMEOUT_SECONDS = 300.0
"""Five minutes to click through Etsy's consent screen, sign in if the browser
was not already, and come back. Long enough not to punish a password manager;
short enough that an abandoned run does not hold a port forever."""

_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>{title}</title>
<body style="font-family: system-ui, sans-serif; margin: 4rem auto; max-width: 32rem">
<h1>{title}</h1>
<p>{message}</p>
</body>
"""


class CallbackError(RuntimeError):
    """The redirect could not be received at all -- a port already in use, or
    nobody came back before the timeout. Distinct from :class:`OAuthError`,
    which means Etsy answered and said no."""


@dataclass(frozen=True)
class Callback:
    code: str
    state: str | None


def wait_for_redirect(
    *,
    redirect_uri: str = REDIRECT_URI,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    monotonic: Any = time.monotonic,
) -> Callback:
    """Serve until Etsy redirects the browser here, then answer with the code."""
    split = urlsplit(redirect_uri)
    path = split.path or "/"
    port = split.port
    if port is None:  # pragma: no cover - the constant always carries one
        raise CallbackError(f"the redirect URI {redirect_uri} names no port")

    result: dict[str, Callback | OAuthError] = {}

    class Handler(_CallbackHandler):
        callback_path = path
        outcomes = result

    deadline = monotonic() + timeout
    with _serve(port, Handler) as server:
        while "value" not in result:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise CallbackError(
                    f"no redirect arrived on port {port} within {timeout:.0f}s. "
                    f"If the browser did not open, run `auth` again and use the URL it prints."
                )
            server.timeout = remaining
            server.handle_request()

    outcome = result["value"]
    if isinstance(outcome, OAuthError):
        raise outcome
    return outcome


class _CallbackHandler(BaseHTTPRequestHandler):
    callback_path: ClassVar[str]
    outcomes: ClassVar[dict[str, Callback | OAuthError]]

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        if request.path != self.callback_path:
            self._respond(404, "Not here", "This is not the callback address.")
            return
        params = parse_qs(request.query)
        error = _first(params, "error")
        if error is not None:
            self.outcomes["value"] = OAuthError(error, _first(params, "error_description"))
            self._respond(
                400, "Sign-in refused", "You can close this tab and return to the terminal."
            )
            return
        code = _first(params, "code")
        if code is None:
            self._respond(400, "Nothing to do", "That redirect carried no authorization code.")
            return
        self.outcomes["value"] = Callback(code=code, state=_first(params, "state"))
        self._respond(200, "Signed in", "You can close this tab and return to the terminal.")

    def _respond(self, status: int, title: str, message: str) -> None:
        body = _PAGE.format(title=title, message=message).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        """Silenced: the default request line on stderr reads like an error."""


def _serve(port: int, handler: type[BaseHTTPRequestHandler]) -> HTTPServer:
    """A server on `127.0.0.1` exactly, never a wildcard: Windows refuses a
    bind only on an exact address match, so a wildcard would let a second
    `auth` run listen beside the first and silently split the redirect.
    `::1` is not answered; browsers fall back to `127.0.0.1`.
    """
    try:
        return _LoopbackServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise CallbackError(
            f"port {port} is already in use, so Etsy's redirect cannot be received. "
            f"The port is not ours to change -- it is registered with the Etsy app as "
            f"part of the callback URL -- so stop whatever is holding it and try again."
        ) from exc


class _LoopbackServer(HTTPServer):
    allow_reuse_address = False
    """`HTTPServer` turns this on; on Windows `SO_REUSEADDR` lets a second
    socket bind a port another process is listening on."""


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None
