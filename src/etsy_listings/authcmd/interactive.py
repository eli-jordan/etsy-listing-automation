"""Sequencing the questions ``auth`` asks, and doing the I/O it decides on.

Three orderings matter here and none of them is arbitrary:

- **The ``.gitignore`` is written before the first secret.** ``auth`` runs
  before ``setup``, so it may be the first thing ever written into this
  directory -- and a directory inside an existing repository is one where a
  ``.env`` written a moment too early is already tracked (PRD 49).
- **Every credential is verified before it is stored**, against its own API:
  Printify's shop list, Etsy's ping, and for the bearer, the token exchange
  itself. Storing an unverified credential produces a workspace that looks
  configured and is not.
- **The browser is opened after the app key pair is known good.** A keystring
  typo surfaces as an Etsy error page mid-consent otherwise, which is a long
  way from the question that caused it.

Every external effect arrives through :class:`Backends`, so the whole flow --
browser included -- runs in a test without a socket or a network.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import typer

from etsy_listings import connections, credentials, prompts
from etsy_listings.authcmd import logic
from etsy_listings.clients.etsy import callback as callback_module
from etsy_listings.clients.etsy import oauth
from etsy_listings.clients.etsy.tokens import TokenStore, utcnow
from etsy_listings.clients.etsy.transport import OAuthClient, Transport
from etsy_listings.clients.printify import PrintifyAuthError
from etsy_listings.clients.printify.models import Shop
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.config.secrets import (
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    EtsyAppKey,
    Secrets,
)
from etsy_listings.workspace import layout


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
ones to renew the third is what teaches people to avoid the command (PRD 14).
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
        _etsy_sign_in(root, app_key, store, back)
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
            shops = back.printify_client(values[0]).shops()
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
        application_id = back.etsy_transport(app_key).ping()
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


def _etsy_sign_in(root: Path, app_key: EtsyAppKey, store: TokenStore, back: Backends) -> None:
    """The browser round trip, or a reason not to make it.

    An existing consent is left alone by default. Re-authorising is harmless
    but not free -- it costs a browser, an Etsy password and a consent screen
    -- and a wizard that spends those on a re-run teaches people not to re-run
    it.
    """
    summary = logic.summarise(store.load(), now=back.now())
    if summary.present:
        typer.echo("")
        typer.echo(f"  {summary.line()}")
        if not prompts.ask_confirm("Sign in to Etsy again?", default=False):
            return

    pkce = oauth.Pkce.generate()
    state = oauth.new_state()
    url = oauth.authorize_url(keystring=app_key.keystring, pkce=pkce, state=state)

    typer.echo("")
    typer.echo("Opening Etsy's consent page in your browser. If it does not open,")
    typer.echo("paste this URL yourself:")
    typer.echo(f"  {url}")
    back.open_browser(url)

    typer.echo(f"Waiting for the redirect to {oauth.REDIRECT_URI} ...")
    redirect = back.wait_for_redirect()
    oauth.check_state(sent=state, received=redirect.state)

    response = back.oauth_client(app_key.keystring).exchange(
        code=redirect.code, verifier=pkce.verifier
    )
    tokens = store.record(response)
    typer.echo(f"  signed in as Etsy user {tokens.user_id}; tokens written to {store.path}")
    if tokens.scope != " ".join(oauth.SCOPES):
        # Etsy grants a subset silently when an app's registration allows
        # less than it asked for, and the shortfall only shows up later as a
        # 403 on one endpoint. Cheaper to read it here.
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


def _report(root: Path, store: TokenStore, back: Backends) -> None:
    secrets = Secrets.load(root / layout.ENV_FILE)
    summary = logic.summarise(store.load(), now=back.now())

    typer.echo(summary.line())
    missing = logic.missing_credentials(secrets)
    if missing:
        typer.echo(f"Missing: {', '.join(missing)}")
    else:
        typer.echo(f"All required credentials present in {secrets.env_file}")
    for name in logic.optional_credentials(secrets):
        typer.echo(f"Optional, not set: {name}")

    warning = logic.renewal_warning(summary)
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
