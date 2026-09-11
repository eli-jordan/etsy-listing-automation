"""The loopback server that catches Etsy's redirect.

One request, one result, then gone. It exists for the few seconds between
opening the browser and the user granting consent, and it takes its address
from :data:`~etsy_listings.clients.etsy.oauth.REDIRECT_URI` rather than a port
constant of its own -- Etsy matches the redirect against a registered string
exactly, so that string is the only thing entitled to say which port this
listens on (PRD 50).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from etsy_listings.clients.etsy.oauth import REDIRECT_URI, OAuthError

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
    """Serve until Etsy redirects the browser here, then answer with the code.

    Requests to any other path are answered 404 and **do not** end the wait:
    a browser asking for `/favicon.ico` used to consume the single request
    this server was willing to handle, and the flow would hang holding a code
    it had thrown away.
    """
    split = urlsplit(redirect_uri)
    path = split.path or "/"
    port = split.port
    if port is None:  # pragma: no cover - the constant always carries one
        raise CallbackError(f"the redirect URI {redirect_uri} names no port")

    result: dict[str, Callback | OAuthError] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
            request = urlsplit(self.path)
            if request.path != path:
                self._respond(404, "Not here", "This is not the callback address.")
                return
            params = parse_qs(request.query)
            error = _first(params, "error")
            if error is not None:
                result["value"] = OAuthError(error, _first(params, "error_description"))
                self._respond(
                    400, "Sign-in refused", "You can close this tab and return to the terminal."
                )
                return
            code = _first(params, "code")
            if code is None:
                self._respond(400, "Nothing to do", "That redirect carried no authorization code.")
                return
            result["value"] = Callback(code=code, state=_first(params, "state"))
            self._respond(200, "Signed in", "You can close this tab and return to the terminal.")

        def _respond(self, status: int, title: str, message: str) -> None:
            body = _PAGE.format(title=title, message=message).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            """Silence. The default writes a request line to stderr, which in
            the middle of a wizard reads like an error."""

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


def _serve(port: int, handler: type[BaseHTTPRequestHandler]) -> HTTPServer:
    """A server on `127.0.0.1`, and nothing wider.

    Two reasons for the specific address rather than a wildcard or a
    dual-stack `[::]`, and the second is the one that decided it.

    A wildcard would accept connections from the network for a server whose
    entire job is a redirect from this machine's own browser. And on Windows,
    binding is only refused for an *exact* address match: a second bind to
    `0.0.0.0` succeeds while another process listens on `127.0.0.1`, and the
    reverse succeeds too. Bound to a wildcard, a second `auth` run would come
    up cleanly beside the first and the authorization code would arrive at
    whichever of the two the browser reached -- a failure with no error
    anywhere. Bound to the exact address, a held port raises, and the user is
    told which port and why it cannot move.

    `localhost` also resolves to `::1`, which this does not answer. Browsers
    fall back to `127.0.0.1` when a connection there is refused, and the
    alternative -- two sockets and a select loop -- is a lot of machinery for
    a case the browser already handles.
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
    """`HTTPServer` turns this **on**, and on Windows that is not the
    politeness it is on Unix: `SO_REUSEADDR` there lets a second socket bind an
    address another process is actively listening on, and which of the two
    receives a given connection is undefined. Inherited as-is, this server
    would come up on a port something else already held."""


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None
