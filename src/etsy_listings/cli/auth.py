"""The ``auth`` wizard: every credential this tool needs, each verified
against its own API before it is stored.

The division of labour with ``setup`` is ADR-0025: **credentials here, ids
there**, and this command runs first because every id ``setup`` discovers
needs a credential to discover it with. This module sequences the questions
and says what happened; finding, proving and storing a credential, the
workspace's credential status and the Etsy grant itself are core's
(:mod:`etsy_listings.core.application.credentials`).

Three orderings matter here and none of them is arbitrary:

- **The ``.gitignore`` is written before the first secret.** ``auth`` runs
  before ``setup``, so it may be the first thing ever written into this
  directory -- and a directory inside an existing repository is one where a
  ``.env`` written a moment too early is already tracked.
- **Every credential is verified before it is stored**, against its own API:
  Printify's shop list, Etsy's ping, and for the bearer, the token exchange
  itself. Storing an unverified credential produces a workspace that looks
  configured and is not. Each is stored as soon as it is proved, so a working
  Printify token survives abandoning the Etsy sign-in.
- **The browser is opened after the app key pair is known good.** A keystring
  typo surfaces as an Etsy error page mid-consent otherwise, which is a long
  way from the question that caused it.

Every external effect arrives through :class:`Backends`, so the whole flow --
browser included -- runs in a test without a socket or a network.
:func:`run_auth` is the interface.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import typer

from etsy_listings.cli import credentials, prompts
from etsy_listings.core import connections
from etsy_listings.core.application import credentials as core_credentials
from etsy_listings.core.application.credentials import TokenSummary
from etsy_listings.core.clients.etsy import callback as callback_module
from etsy_listings.core.clients.etsy import oauth
from etsy_listings.core.clients.etsy.tokens import TokenStore, utcnow
from etsy_listings.core.clients.etsy.transport import OAuthClient, Transport
from etsy_listings.core.clients.printify import PrintifyAuthError
from etsy_listings.core.clients.printify.models import Shop
from etsy_listings.core.clients.printify.protocol import PrintifyClient
from etsy_listings.core.config.secrets import (
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    EtsyAppKey,
)


@dataclass(frozen=True)
class Backends:
    """Everything that leaves the process, in one injectable value.

    A single object rather than six keyword arguments: a test replaces the two
    it cares about and inherits the rest, and a new external effect does not
    change the signature of every caller.
    """

    printify_client: Callable[[str], PrintifyClient] = connections.printify_client_for
    etsy_transport: Callable[[EtsyAppKey], Transport] = Transport
    oauth_client: Callable[[str], OAuthClient] = OAuthClient
    wait_for_redirect: Callable[[], callback_module.Callback] = callback_module.wait_for_redirect
    open_browser: Callable[[str], bool] = webbrowser.open
    now: Callable[[], datetime] = utcnow


Part = Literal["printify", "etsy", "anthropic"]

ALL_PARTS: tuple[Part, ...] = ("printify", "etsy", "anthropic")
"""The credentials `auth` knows how to capture, in the order it asks for them.

Printify first because it is the one every phase so far needs; Anthropic last
because nothing needs it yet. A part can be run on its own (`auth etsy`) --
one credential expiring is the ordinary case, and walking past two working
ones to renew the third is what teaches people to avoid the command.
"""


def run_auth(
    root: Path,
    *,
    backends: Backends | None = None,
    check: bool = False,
    parts: Sequence[Part] = ALL_PARTS,
) -> None:
    """Capture (or report on) the credentials named by ``parts``.

    ``check`` reports and writes nothing -- it is the answer to "am I still
    signed in?", which should never be a question you have to risk changing
    something to ask.
    """
    back = backends or Backends()
    root.mkdir(parents=True, exist_ok=True)
    store = _token_store(root, back)

    if check:
        _report(root, store, back)
        return

    typer.echo(f"Credentials for the workspace in {root}")
    credentials.announce_gitignore(root)

    if "printify" in parts:
        _printify_token(root, back)
    if "etsy" in parts:
        # The key pair and the sign-in are one part, not two: the browser flow
        # needs the keystring, and a `auth etsy` that captured a key pair
        # without signing in would leave the half-configured state the whole
        # command exists to avoid.
        app_key = _etsy_app_key(root, back)
        _etsy_sign_in(app_key, store, back)
    if "anthropic" in parts:
        _anthropic_key(root)

    typer.echo("")
    _report(root, store, back)
    if tuple(parts) == ALL_PARTS:
        typer.echo("")
        typer.echo("Next: `etsy-listings setup` writes the workspace and reads back the shop ids.")


# --------------------------------------------------------------- credentials


def _printify_token(root: Path, back: Backends) -> None:
    def verify(values: tuple[str, ...]) -> tuple[list[Shop], str]:
        try:
            shops = core_credentials.verify_printify_token(
                values[0], client_for=back.printify_client
            )
        except PrintifyAuthError as exc:
            credentials.refuse(str(exc), command="auth")
        return shops, f"verified -- the token can reach {len(shops)} shop(s)."

    captured = credentials.capture(
        root, credentials.PRINTIFY, verify=verify, command="auth", verify_reused=False
    )
    credentials.store(root, credentials.PRINTIFY, captured)


def _etsy_app_key(root: Path, back: Backends) -> EtsyAppKey:
    """The keystring and shared secret, verified together by one ping."""

    def verify(values: tuple[str, ...]) -> tuple[EtsyAppKey, str]:
        app_key = EtsyAppKey(values[0], values[1])
        application_id = core_credentials.verify_etsy_app_key(
            app_key, transport_for=back.etsy_transport
        )
        return app_key, f"verified -- Etsy application {application_id}."

    captured = credentials.capture(
        root,
        credentials.ETSY_APP_KEY,
        verify=verify,
        command="auth",
        verify_reused=False,
        reuse_message=f"{ETSY_KEYSTRING_VAR} and {ETSY_SHARED_SECRET_VAR} already set.",
    )
    credentials.store(root, credentials.ETSY_APP_KEY, captured)
    # Rebuilt from the values rather than taken from `proof`: a reused pair is
    # not re-pinged, so there is no proof to take.
    return EtsyAppKey(captured.values[0], captured.values[1])


def _etsy_sign_in(app_key: EtsyAppKey, store: TokenStore, back: Backends) -> None:
    """The browser round trip, or a reason not to make it.

    An existing consent is left alone by default. Re-authorising is harmless
    but not free -- it costs a browser, an Etsy password and a consent screen
    -- and a wizard that spends those on a re-run teaches people not to re-run
    it.
    """
    summary = core_credentials.summarise(store.load(), now=back.now())
    if summary.present:
        typer.echo("")
        typer.echo(f"  {summary_line(summary)}")
        if not prompts.ask_confirm("Sign in to Etsy again?", default=False):
            return

    sign_in = core_credentials.begin_etsy_sign_in(app_key)

    # Presenting the human step is the CLI's; the grant on either side of it
    # is core's (ADR-0026, ADR-0027).
    typer.echo("")
    typer.echo("Opening Etsy's consent page in your browser. If it does not open,")
    typer.echo("paste this URL yourself:")
    typer.echo(f"  {sign_in.url}")
    back.open_browser(sign_in.url)

    typer.echo(f"Waiting for the redirect to {oauth.REDIRECT_URI} ...")
    signed_in = core_credentials.complete_etsy_sign_in(
        sign_in,
        back.wait_for_redirect(),
        oauth_client=back.oauth_client(app_key.keystring),
        tokens=store,
    )
    tokens = signed_in.tokens
    typer.echo(f"  signed in as Etsy user {tokens.user_id}; tokens written to {store.path}")
    if not signed_in.granted_every_scope:
        typer.echo(f"  note: Etsy granted the scopes `{tokens.scope}`")


def _anthropic_key(root: Path) -> None:
    """Optional, and asked last.

    Nothing before Phase 4 uses it, so a blank answer is a complete run rather
    than a skipped step -- and unverified, because Anthropic has no free
    endpoint that proves a key without spending on one.
    """
    captured = credentials.capture(
        root,
        credentials.ANTHROPIC,
        verify=credentials.nothing_to_prove,
        command="auth",
        verify_reused=False,
    )
    credentials.store(root, credentials.ANTHROPIC, captured)


# -------------------------------------------------------------------- report


def summary_line(summary: TokenSummary) -> str:
    """The stored Etsy consent as the one line ``auth`` prints about it."""
    if not summary.present:
        return "Etsy sign-in: none stored"
    access = "valid" if summary.access_valid else "expired (refreshed on next use)"
    return (
        f"Etsy sign-in: user {summary.user_id}, access token {access}, "
        f"consent good for {summary.refresh_days} more days"
    )


def renewal_warning(summary: TokenSummary) -> str | None:
    """The line to print when the 90-day clock is nearly up, or ``None``."""
    if not summary.renewal_due:
        return None
    return (
        f"Etsy consent expires in {summary.refresh_days} days. "
        f"Run `etsy-listings auth` before then to renew it without interrupting a run."
    )


def _report(root: Path, store: TokenStore, back: Backends) -> None:
    status = core_credentials.credential_status(root, tokens=store, now=back.now())

    typer.echo(summary_line(status.sign_in))
    if status.missing:
        typer.echo(f"Missing: {', '.join(status.missing)}")
    else:
        typer.echo(f"All required credentials present in {status.env_file}")
    for name in status.optional_missing:
        typer.echo(f"Optional, not set: {name}")

    warning = renewal_warning(status.sign_in)
    if warning:
        typer.echo(warning)


def _token_store(root: Path, back: Backends) -> TokenStore:
    """This workspace's token store, with `auth`'s own OAuth client and clock.

    Both are ``Backends`` fields so the whole flow runs without a socket; the
    store's shape -- where the file lives, and that its refresh resolves the
    keystring lazily so `auth --check` works on a workspace holding no
    credentials at all -- is ``connections``'.
    """
    return connections.etsy_token_store(root, oauth=back.oauth_client, now=back.now)
